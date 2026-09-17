from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from packages.interfaces.pending_action import (
    ActionState,
    ConfirmationResult,
    ConfirmationStatus,
    PendingAction,
)
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import (
    PermissionDecision,
    RiskLevel,
    SafetyResult,
)
from services.api.main import app
from services.brain.brain import ECHOBrain, echo_brain
from services.brain.execution import ExecutionEngine, execution_engine
from services.brain.tool_router import ToolRouter
from services.security.pending_action_manager import (
    PendingActionManager,
    pending_action_manager,
)
from services.security.safety_engine import SafetyEngine


@pytest.fixture(autouse=True)
def clean_pending_action_manager():
    """Reset the global pending action store before and after each test."""
    pending_action_manager.clear()
    yield
    pending_action_manager.clear()


@pytest.fixture
def local_manager():
    """Create an isolated PendingActionManager with short TTL for testing."""
    return PendingActionManager(default_ttl=1.0, max_stored_actions=10)


# ==========================================
# 1. PENDING ACTION MODEL & LIFECYCLE
# ==========================================

def test_pending_action_creation_and_attributes(local_manager):
    args = {"path": "C:\\safe\\test.txt"}
    action = local_manager.create_pending_action(
        tool_name="delete_file",
        arguments=args,
        risk_level=RiskLevel.SENSITIVE,
        request_id="req-123",
        step_number=1,
    )

    assert isinstance(action, PendingAction)
    assert len(action.action_id) > 0
    assert action.tool_name == "delete_file"
    assert action.arguments == args
    assert action.risk_level == RiskLevel.SENSITIVE
    assert action.state == ActionState.PENDING
    assert action.request_id == "req-123"
    assert action.step_number == 1
    assert action.is_pending() is True
    assert action.is_expired() is False

    # Immutability: caller mutating original dict does not mutate action.arguments
    args["path"] = "C:\\hacked.txt"
    assert action.arguments["path"] == "C:\\safe\\test.txt"


def test_pending_action_unique_ids(local_manager):
    ids = set()
    for _ in range(50):
        act = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE)
        ids.add(act.action_id)
    assert len(ids) == 50


def test_pending_action_ttl_and_expiration(local_manager):
    # Action with very short TTL
    action = local_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\test.txt"},
        risk_level=RiskLevel.SENSITIVE,
        ttl_seconds=0.1,
    )

    assert action.is_expired() is False
    assert action.is_pending() is True

    time.sleep(0.15)

    assert action.is_expired() is True
    assert action.is_pending() is False

    # get_action marks state EXPIRED
    retrieved = local_manager.get_action(action.action_id)
    assert retrieved is not None
    assert retrieved.state == ActionState.EXPIRED


def test_pending_action_to_dict_format(local_manager):
    action = local_manager.create_pending_action(
        tool_name="execute_command",
        arguments={"command": "git", "arguments": ["status"]},
        risk_level=RiskLevel.SENSITIVE,
        request_id="req-456",
        step_number=2,
    )

    d = action.to_dict()
    assert d["action_id"] == action.action_id
    assert d["tool"] == "execute_command"
    assert d["arguments"] == {"command": "git", "arguments": ["status"]}
    assert d["risk_level"] == "sensitive"
    assert d["state"] == "pending"
    assert d["step_number"] == 2
    assert d["request_id"] == "req-456"
    assert "created_at" in d
    assert "expires_at" in d


# ==========================================
# 2. ATOMIC CLAIMING & SINGLE-USE GUARANTEE
# ==========================================

def test_atomic_claim_succeeds_once(local_manager):
    action = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE)

    # First claim succeeds
    claimed, act, status, msg = local_manager.claim_for_execution(action.action_id)
    assert claimed is True
    assert act.state == ActionState.CONFIRMED
    assert status == ConfirmationStatus.CONFIRMED

    # Second claim fails (replay protection)
    claimed2, act2, status2, msg2 = local_manager.claim_for_execution(action.action_id)
    assert claimed2 is False
    assert status2 == ConfirmationStatus.ALREADY_PROCESSED


def test_claim_expired_action_fails(local_manager):
    action = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE, ttl_seconds=0.05)
    time.sleep(0.1)

    claimed, act, status, msg = local_manager.claim_for_execution(action.action_id)
    assert claimed is False
    assert status == ConfirmationStatus.EXPIRED
    assert act.state == ActionState.EXPIRED


def test_claim_nonexistent_action_fails(local_manager):
    claimed, act, status, msg = local_manager.claim_for_execution("nonexistent-id")
    assert claimed is False
    assert status == ConfirmationStatus.NOT_FOUND


def test_claim_invalid_id_fails(local_manager):
    claimed, act, status, msg = local_manager.claim_for_execution("")
    assert claimed is False
    assert status == ConfirmationStatus.INVALID


def test_concurrent_claim_guarantees_single_execution(local_manager):
    action = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE)

    results = []

    def try_claim():
        return local_manager.claim_for_execution(action.action_id)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_claim) for _ in range(10)]
        for f in futures:
            results.append(f.result())

    # Exactly 1 thread must succeed; all 9 others must fail
    success_count = sum(1 for res in results if res[0] is True)
    failure_count = sum(1 for res in results if res[0] is False)

    assert success_count == 1
    assert failure_count == 9


# ==========================================
# 3. CANCELLATION
# ==========================================

def test_cancel_pending_action_success(local_manager):
    action = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE)

    res = local_manager.cancel_action(action.action_id)
    assert res.success is True
    assert res.status == ConfirmationStatus.CANCELLED
    assert action.state == ActionState.CANCELLED

    # Cancelled action cannot be claimed for execution
    claimed, _, status, _ = local_manager.claim_for_execution(action.action_id)
    assert claimed is False
    assert status == ConfirmationStatus.ALREADY_PROCESSED


def test_cancel_action_idempotent(local_manager):
    action = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE)

    res1 = local_manager.cancel_action(action.action_id)
    assert res1.success is True
    assert res1.status == ConfirmationStatus.CANCELLED

    res2 = local_manager.cancel_action(action.action_id)
    assert res2.success is True
    assert res2.status == ConfirmationStatus.CANCELLED
    assert "already cancelled" in res2.message.lower()


def test_cancel_nonexistent_action(local_manager):
    res = local_manager.cancel_action("bad-id")
    assert res.success is False
    assert res.status == ConfirmationStatus.NOT_FOUND


def test_cancel_invalid_id(local_manager):
    res = local_manager.cancel_action("")
    assert res.success is False
    assert res.status == ConfirmationStatus.INVALID


def test_cancel_already_executed_action_rejected(local_manager):
    action = local_manager.create_pending_action("delete_file", {}, RiskLevel.SENSITIVE)
    local_manager.claim_for_execution(action.action_id)
    local_manager.mark_executed(action.action_id, result="ok")

    res = local_manager.cancel_action(action.action_id)
    assert res.success is False
    assert res.status == ConfirmationStatus.ALREADY_PROCESSED


# ==========================================
# 4. BOUNDED STORAGE & PRUNING
# ==========================================

def test_manager_bounded_capacity_prunes_stale():
    mgr = PendingActionManager(default_ttl=10.0, max_stored_actions=5)

    actions = []
    for i in range(5):
        act = mgr.create_pending_action("tool", {"i": i}, RiskLevel.SENSITIVE)
        actions.append(act)

    # Cancel the first two so they are eligible for pruning
    mgr.cancel_action(actions[0].action_id)
    mgr.cancel_action(actions[1].action_id)

    # Creating a 6th action triggers pruning of completed actions
    act6 = mgr.create_pending_action("tool", {"i": 6}, RiskLevel.SENSITIVE)
    assert act6.action_id in mgr._actions
    assert len(mgr._actions) <= 5


# ==========================================
# 5. EXECUTION ENGINE CONFIRM & RESUME
# ==========================================

def test_execution_engine_creates_pending_action_on_confirm():
    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = SafetyResult(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
        reason="Needs approval",
        operation="delete_file",
    )

    engine = ExecutionEngine(safety_engine=mock_safety)
    req = Request(user_input="Delete file")
    req.selected_tools = ["delete_file"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete file",
                tool_name="delete_file",
                arguments={"path": "C:\\safe\\file.txt"},
            )
        ],
    )

    res = engine.execute(req, plan)
    assert res.success is False
    assert res.requires_confirmation is True
    assert res.pending_action is not None
    assert "action_id" in res.pending_action
    assert res.pending_action["tool"] == "delete_file"
    assert res.pending_action["arguments"] == {"path": "C:\\safe\\file.txt"}
    assert res.pending_action["state"] == "pending"

    # Verify action was stored in manager
    stored = engine.pending_action_manager.get_action(res.pending_action["action_id"])
    assert stored is not None
    assert stored.tool_name == "delete_file"


def test_execution_engine_resumes_confirmed_action():
    mock_router = MagicMock()
    mock_router.execute_tool.return_value = {"status": "deleted", "path": "C:\\safe\\file.txt"}

    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = SafetyResult(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
        reason="Needs approval",
        operation="delete_file",
    )

    engine = ExecutionEngine(router=mock_router, safety_engine=mock_safety)
    action = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\safe\\file.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    confirm_res = engine.resume_pending_action(action.action_id)
    assert confirm_res.success is True
    assert confirm_res.status == ConfirmationStatus.CONFIRMED
    assert confirm_res.result == {"status": "deleted", "path": "C:\\safe\\file.txt"}
    assert action.state == ActionState.EXECUTED
    mock_router.execute_tool.assert_called_once_with(
        "delete_file",
        message=None,
        path="C:\\safe\\file.txt",
    )


def test_resume_replays_are_blocked():
    mock_router = MagicMock()
    mock_router.execute_tool.return_value = "ok"

    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = SafetyResult(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
        reason="Needs approval",
        operation="delete_file",
    )

    engine = ExecutionEngine(router=mock_router, safety_engine=mock_safety)
    action = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\safe\\file.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    # First resume succeeds
    res1 = engine.resume_pending_action(action.action_id)
    assert res1.success is True

    # Second resume is blocked as ALREADY_PROCESSED
    res2 = engine.resume_pending_action(action.action_id)
    assert res2.success is False
    assert res2.status == ConfirmationStatus.ALREADY_PROCESSED
    assert mock_router.execute_tool.call_count == 1


def test_resume_safety_recheck_blocks_dangerous_action():
    mock_router = MagicMock()
    mock_safety = MagicMock()

    # SafetyEngine re-check returns BLOCK (e.g. policy change or blocked target)
    mock_safety.evaluate.return_value = SafetyResult(
        decision=PermissionDecision.BLOCK,
        risk_level=RiskLevel.CRITICAL,
        reason="Prohibited by security policy",
        operation="delete_file",
    )

    engine = ExecutionEngine(router=mock_router, safety_engine=mock_safety)
    action = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\Windows\\system32"},
        risk_level=RiskLevel.SENSITIVE,
    )

    res = engine.resume_pending_action(action.action_id)
    assert res.success is False
    assert res.status == ConfirmationStatus.FAILED
    assert "blocked by the security policy" in res.message
    assert action.state == ActionState.FAILED
    mock_router.execute_tool.assert_not_called()


def test_resume_parameter_validation_failure():
    mock_router = MagicMock()
    engine = ExecutionEngine(router=mock_router)

    # Corrupted / invalid arguments for tool invocation
    action = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={},  # missing required 'path'
        risk_level=RiskLevel.SENSITIVE,
    )

    res = engine.resume_pending_action(action.action_id)
    assert res.success is False
    assert res.status == ConfirmationStatus.FAILED
    assert "validation failed" in res.message.lower()
    assert action.state == ActionState.FAILED
    mock_router.execute_tool.assert_not_called()


def test_resume_tool_execution_exception_handled():
    mock_router = MagicMock()
    mock_router.execute_tool.side_effect = PermissionError("OS Access Denied")

    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = SafetyResult(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
        reason="Needs approval",
        operation="delete_file",
    )

    engine = ExecutionEngine(router=mock_router, safety_engine=mock_safety)
    action = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\safe\\file.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    res = engine.resume_pending_action(action.action_id)
    assert res.success is False
    assert res.status == ConfirmationStatus.FAILED
    assert "Tool execution failed" in res.message
    assert "OS Access Denied" in res.error
    assert action.state == ActionState.FAILED


def test_cancel_pending_action_via_execution_engine():
    engine = ExecutionEngine()
    action = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\safe\\file.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    res = engine.cancel_pending_action(action.action_id)
    assert res.success is True
    assert res.status == ConfirmationStatus.CANCELLED
    assert action.state == ActionState.CANCELLED


# ==========================================
# 6. BRAIN COORDINATOR INTEGRATION
# ==========================================

@pytest.mark.anyio
async def test_brain_confirm_action_integration():
    brain = ECHOBrain()
    action = brain.get_pending_action("nonexistent")
    assert action is None

    # Create a real pending action through ExecutionEngine
    act = execution_engine.pending_action_manager.create_pending_action(
        tool_name="read_file",
        arguments={"path": "C:\\safe\\file.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    found = brain.get_pending_action(act.action_id)
    assert found is not None
    assert found.action_id == act.action_id

    # Cancel via brain
    cancel_res = brain.cancel_action(act.action_id)
    assert cancel_res.success is True
    assert cancel_res.status == ConfirmationStatus.CANCELLED


@pytest.mark.anyio
async def test_brain_process_handles_confirm_command():
    mock_router = MagicMock()
    mock_router.execute_tool.return_value = "file deleted successfully"

    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = SafetyResult(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
        reason="Needs approval",
        operation="delete_file",
    )

    engine = ExecutionEngine(router=mock_router, safety_engine=mock_safety)
    act = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\safe\\test.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    brain = ECHOBrain()
    # Inject engine
    import services.brain.brain as brain_mod
    orig_engine = brain_mod.execution_engine
    brain_mod.execution_engine = engine

    try:
        resp = await brain.process(f"/confirm {act.action_id}")
        assert "confirmed and executed successfully" in resp
        assert "file deleted successfully" in resp
    finally:
        brain_mod.execution_engine = orig_engine


@pytest.mark.anyio
async def test_brain_process_handles_cancel_command():
    engine = ExecutionEngine()
    act = engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\safe\\test.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    brain = ECHOBrain()
    import services.brain.brain as brain_mod
    orig_engine = brain_mod.execution_engine
    brain_mod.execution_engine = engine

    try:
        resp = await brain.process(f"/cancel {act.action_id}")
        assert "has been cancelled" in resp
        assert act.state == ActionState.CANCELLED
    finally:
        brain_mod.execution_engine = orig_engine


# ==========================================
# 7. FASTAPI REST API ENDPOINTS
# ==========================================

def test_api_confirm_endpoint():
    client = TestClient(app)

    # 1. Non-existent action
    resp = client.post("/actions/confirm", json={"action_id": "missing-id"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["status"] == "not_found"

    # 2. Create pending action
    act = echo_brain.confirm_action  # verify echo_brain is wired
    act = execution_engine.pending_action_manager.create_pending_action(
        tool_name="time",
        arguments={},
        risk_level=RiskLevel.SENSITIVE,
    )

    # 3. Confirm via API
    resp2 = client.post("/actions/confirm", json={"action_id": act.action_id})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["success"] is True
    assert data2["status"] == "confirmed"
    assert data2["action_id"] == act.action_id


def test_api_cancel_endpoint():
    client = TestClient(app)

    act = execution_engine.pending_action_manager.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "C:\\test.txt"},
        risk_level=RiskLevel.SENSITIVE,
    )

    resp = client.post("/actions/cancel", json={"action_id": act.action_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "cancelled"
    assert act.state == ActionState.CANCELLED


def test_api_get_action_detail_endpoint():
    client = TestClient(app)

    act = execution_engine.pending_action_manager.create_pending_action(
        tool_name="execute_command",
        arguments={"command": "git", "arguments": ["status"]},
        risk_level=RiskLevel.SENSITIVE,
        step_number=1,
    )

    resp = client.get(f"/actions/{act.action_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_id"] == act.action_id
    assert data["tool"] == "execute_command"
    assert data["arguments"] == {"command": "git", "arguments": ["status"]}
    assert data["risk_level"] == "sensitive"
    assert data["state"] == "pending"

    # Missing action returns 404
    resp_missing = client.get("/actions/bad-id-xyz")
    assert resp_missing.status_code == 404
