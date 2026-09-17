from pathlib import Path
import pytest

from packages.common.capability_registry import capability_registry
from packages.common.tool_registry import tool_registry
from packages.interfaces.execution import ExecutionResult
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.tool_invocation import ToolInvocation
from services.brain.execution import ExecutionEngine
from services.brain.tool_selector import ToolSelector
from services.brain.verification import VerificationEngine
from services.desktop.filesystem import FilesystemService
from services.desktop.policy import DesktopSecurityPolicy, PolicyErrorCode
from services.security.risk import RiskClassifier
from services.security.safety_engine import SafetyEngine


@pytest.fixture
def isolated_env(tmp_path: Path):
    """Sets up an isolated test environment for tool integration."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    workspace = sandbox / "workspace"
    workspace.mkdir()

    docs = sandbox / "docs"
    docs.mkdir()

    policy = DesktopSecurityPolicy(
        authorized_roots=[workspace, docs],
        include_default_roots=False,
    )
    service = FilesystemService(policy=policy)

    return {
        "sandbox": sandbox,
        "workspace": workspace,
        "docs": docs,
        "policy": policy,
        "service": service,
    }


# 19. Delete protected target rejected
def test_delete_protected_target_rejected(isolated_env):
    service: FilesystemService = isolated_env["service"]
    workspace: Path = isolated_env["workspace"]

    # Protected file like .env inside workspace
    protected = workspace / ".env"
    protected.write_text("SECRET=123")

    with pytest.raises(Exception) as exc_info:
        service.delete_file(protected)

    assert "prohibited" in str(exc_info.value).lower() or "secrets" in str(exc_info.value).lower()
    assert protected.exists()


# 20. Delete normal target requires safety confirmation
def test_delete_normal_target_requires_safety_confirmation(isolated_env):
    workspace: Path = isolated_env["workspace"]
    target_file = workspace / "test_delete.txt"
    target_file.write_text("data")

    engine = ExecutionEngine()
    request = Request(user_input="Delete file")
    request.selected_tools = ["delete_file"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete normal target",
                tool_name="delete_file",
                arguments={"path": str(target_file)},
            )
        ],
    )

    result = engine.execute(request, plan)

    assert result.success is False
    assert result.requires_confirmation is True
    assert result.pending_action is not None
    assert result.pending_action["tool"] == "delete_file"
    assert result.pending_action["arguments"]["path"] == str(target_file)
    assert "confirmation is required" in result.error.lower()
    # File must NOT have been deleted
    assert target_file.exists()


# 25. ToolSelector integration
def test_tool_selector_creates_valid_tool_invocation_for_filesystem():
    selector = ToolSelector()

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Read config",
                tool_name="read_file",
                arguments={"path": "C:/safe/file.txt"},
            ),
            PlanStep(
                step_number=2,
                description="Copy file",
                tool_name="copy_file",
                arguments={"source": "C:/safe/a.txt", "destination": "C:/safe/b.txt"},
            ),
        ],
    )

    invocations = selector.select_invocations(plan)
    assert len(invocations) == 2
    assert invocations[0].tool_name == "read_file"
    assert invocations[0].arguments == {"path": "C:/safe/file.txt"}
    assert invocations[1].tool_name == "copy_file"
    assert invocations[1].arguments == {
        "source": "C:/safe/a.txt",
        "destination": "C:/safe/b.txt",
    }


def test_tool_invocation_rejects_missing_parameters():
    # read_file without path
    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="read_file", arguments={})
    assert "requires 'path'" in str(exc.value)

    # copy_file without destination
    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="copy_file", arguments={"source": "a.txt"})
    assert "requires 'destination'" in str(exc.value)


# 26. SafetyEngine integration
def test_safety_engine_evaluates_filesystem_tool_risk():
    safety = SafetyEngine()

    # SAFE tools -> ALLOW
    res_read = safety.evaluate("read_file", arguments={"path": "notes.txt"})
    assert res_read.risk_level == RiskLevel.SAFE
    assert res_read.decision == PermissionDecision.ALLOW

    res_list = safety.evaluate("list_folder", arguments={"path": "docs"})
    assert res_list.risk_level == RiskLevel.SAFE
    assert res_list.decision == PermissionDecision.ALLOW

    res_create_folder = safety.evaluate("create_folder", arguments={"path": "docs/sub"})
    assert res_create_folder.risk_level == RiskLevel.SAFE
    assert res_create_folder.decision == PermissionDecision.ALLOW

    # MODERATE tools -> ALLOW
    res_copy = safety.evaluate(
        "copy_file", arguments={"source": "a.txt", "destination": "b.txt"}
    )
    assert res_copy.risk_level == RiskLevel.MODERATE
    assert res_copy.decision == PermissionDecision.ALLOW

    # SENSITIVE tools -> CONFIRM
    res_create_file = safety.evaluate("create_file", arguments={"path": "a.txt"})
    assert res_create_file.risk_level == RiskLevel.SENSITIVE
    assert res_create_file.decision == PermissionDecision.CONFIRM

    res_rename = safety.evaluate(
        "rename_file", arguments={"source": "a.txt", "destination": "b.txt"}
    )
    assert res_rename.risk_level == RiskLevel.SENSITIVE
    assert res_rename.decision == PermissionDecision.CONFIRM

    res_move = safety.evaluate(
        "move_file", arguments={"source": "a.txt", "destination": "b.txt"}
    )
    assert res_move.risk_level == RiskLevel.SENSITIVE
    assert res_move.decision == PermissionDecision.CONFIRM

    res_delete = safety.evaluate("delete_file", arguments={"path": "a.txt"})
    assert res_delete.risk_level == RiskLevel.SENSITIVE
    assert res_delete.decision == PermissionDecision.CONFIRM


# 27. ExecutionEngine integration
def test_execution_engine_executes_allowed_filesystem_tools(isolated_env, monkeypatch):
    service: FilesystemService = isolated_env["service"]
    workspace: Path = isolated_env["workspace"]
    # Point global service to isolated service for testing
    import services.brain.tools.filesystem_tools as fs_tools

    monkeypatch.setattr(fs_tools, "filesystem_service", service)

    sample = workspace / "hello.txt"
    sample.write_text("ECHO file test")

    engine = ExecutionEngine()
    request = Request(user_input="Read file")
    request.selected_tools = ["read_file"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Read file",
                tool_name="read_file",
                arguments={"path": str(sample)},
            )
        ],
    )

    result = engine.execute(request, plan)
    assert result.success is True
    assert result.result == ["ECHO file test"]
    assert request.status == RequestStatus.COMPLETED


# 28. VerificationEngine integration
def test_verification_engine_verifies_filesystem_postconditions(tmp_path: Path):
    verifier = VerificationEngine()
    test_file = tmp_path / "created.txt"
    test_file.write_text("content")

    request = Request(user_input="Create file")
    exec_res = ExecutionResult(
        success=True,
        result=[
            {
                "operation": "create_file",
                "path": str(test_file),
                "status": "created",
                "verified": True,
            }
        ],
    )

    # File exists -> verification succeeds
    v_res = verifier.verify(request, exec_res)
    assert v_res.success is True

    # If the file was unexpectedly absent -> verification must fail!
    test_file.unlink()
    v_res_fail = verifier.verify(request, exec_res)
    assert v_res_fail.success is False
    assert "Verification failed" in v_res_fail.error
    assert request.status == RequestStatus.FAILED


def test_verification_engine_verifies_delete_postcondition(tmp_path: Path):
    verifier = VerificationEngine()
    deleted_path = tmp_path / "deleted.txt"

    request = Request(user_input="Delete file")
    exec_res = ExecutionResult(
        success=True,
        result=[
            {
                "operation": "delete_file",
                "path": str(deleted_path),
                "status": "deleted",
                "verified": True,
            }
        ],
    )

    # Path does not exist -> verified!
    v_res = verifier.verify(request, exec_res)
    assert v_res.success is True

    # If path still exists -> verification must fail!
    deleted_path.write_text("still here")
    v_res_fail = verifier.verify(request, exec_res)
    assert v_res_fail.success is False
    assert "still exists" in v_res_fail.error
