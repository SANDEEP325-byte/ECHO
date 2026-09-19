"""Canonical E2E integration tests for ECHO Desktop Subsystem (Phase 9B).

Exercises the desktop pipeline through ECHOBrain:
Request → Planner → ToolSelector → ExecutionEngine → SafetyEngine → ToolRouter → Desktop Tools → VerificationEngine → ResponseGenerator
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from packages.interfaces.pending_action import ActionState
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from services.brain.brain import ECHOBrain
from services.security.pending_action_manager import pending_action_manager


@pytest.mark.anyio
async def test_e2e_desktop_safe_read_executes_unconfirmed(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify safe read operations execute directly through the pipeline without confirmation."""
    brain = fresh_echo_brain
    test_file = isolated_workspace / "sample.txt"
    test_file.write_text("Hello ECHO Desktop!", encoding="utf-8")

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Read safe text file",
                tool_name="read_file",
                arguments={"path": str(test_file)},
            )
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Read sample.txt")
        resp = await brain.process(req)

        assert req.status == RequestStatus.COMPLETED
        assert "Hello ECHO Desktop!" in str(resp)


@pytest.mark.anyio
async def test_e2e_desktop_write_halts_for_confirmation_and_resumes(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify sensitive file write halts for confirmation, and resumes on /confirm with disk verification."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    target_file = isolated_workspace / "created_by_echo.txt"

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create new file",
                tool_name="create_file",
                arguments={"path": str(target_file), "content": "Confirmed data content"},
            )
        ],
    )

    # 1. Initial request must halt for user confirmation
    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Create created_by_echo.txt with Confirmed data content")
        prompt = await brain.process(req)

        # File must not exist yet
        assert not target_file.exists()
        assert "confirm" in prompt.lower()

        # Action must be registered in PendingActionManager
        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # 2. Issue /confirm <action_id>
    confirm_resp = await brain.process(f"/confirm {action_id}")
    assert "confirmed and executed successfully" in confirm_resp.lower()

    # 3. Independent physical verification on disk
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "Confirmed data content"


@pytest.mark.anyio
async def test_e2e_desktop_delete_halts_and_cancels_cleanly(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify sensitive delete operation halts, and /cancel permanently prevents execution."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    target_file = isolated_workspace / "to_delete.txt"
    target_file.write_text("Do not delete me yet", encoding="utf-8")

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete file",
                tool_name="delete_file",
                arguments={"path": str(target_file)},
            )
        ],
    )

    # 1. Request halts for confirmation
    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Delete to_delete.txt")
        prompt = await brain.process(req)
        assert "confirm" in prompt.lower()
        assert target_file.exists()

        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # 2. Cancel the action
    cancel_resp = await brain.process(f"/cancel {action_id}")
    assert "has been cancelled" in cancel_resp

    # File still exists on disk
    assert target_file.exists()

    # Attempting to resume cancelled ticket fails
    resume_res = brain.confirm_action(action_id)
    assert resume_res.success is False
    assert target_file.exists()


@pytest.mark.anyio
async def test_e2e_desktop_protected_target_hard_blocked(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify protected system files (.env, id_rsa) are blocked by policy even if confirmed."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    protected_file = isolated_workspace / ".env"
    protected_file.write_text("SECRET=my_key", encoding="utf-8")

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete protected file",
                tool_name="delete_file",
                arguments={"path": str(protected_file)},
            )
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Delete .env")
        prompt = await brain.process(req)

        # 1. Must halt for confirmation
        assert "confirm" in prompt.lower()
        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # 2. Even if confirmed, desktop security policy blocks deletion of .env
    confirm_resp = await brain.process(f"/confirm {action_id}")
    assert (
        "prohibited" in confirm_resp.lower()
        or "failed" in confirm_resp.lower()
        or "error" in confirm_resp.lower()
    )

    # 3. File remains completely intact on disk
    assert protected_file.exists()
    assert protected_file.read_text(encoding="utf-8") == "SECRET=my_key"


@pytest.mark.anyio
async def test_e2e_desktop_command_execution_and_confirmation(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify command execution halts for confirmation and returns verified exit code 0."""
    brain = fresh_echo_brain
    pending_action_manager.clear()

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Execute safe python version check",
                tool_name="execute_command",
                arguments={"command": "python", "arguments": ["--version"]},
            )
        ],
    )

    # 1. Command requires confirmation
    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Run python --version")
        prompt = await brain.process(req)
        assert "confirm" in prompt.lower()

        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # 2. Confirm command
    confirm_resp = await brain.process(f"/confirm {action_id}")
    assert "confirmed and executed successfully" in confirm_resp.lower()


@pytest.mark.anyio
async def test_e2e_desktop_dangerous_command_blocked(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify unapproved shell commands (rm, format) are rejected by policy even if confirmed."""
    brain = fresh_echo_brain
    pending_action_manager.clear()

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Run catastrophic command",
                tool_name="execute_command",
                arguments={"command": "rm", "arguments": ["-rf", "/"]},
            )
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Run rm -rf /")
        prompt = await brain.process(req)

        # 1. Halts for confirmation
        assert "confirm" in prompt.lower()
        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # 2. Confirming an unallowlisted command family is rejected by command policy
    confirm_resp = await brain.process(f"/confirm {action_id}")
    assert "not in the approved allowlist" in confirm_resp or "failed" in confirm_resp.lower()


@pytest.mark.anyio
async def test_e2e_desktop_verification_failure_detected(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that when an expected post-condition is unsatisfied, VerificationEngine reports failure cleanly."""
    from services.brain.tools.filesystem_tools import filesystem_service

    brain = fresh_echo_brain
    pending_action_manager.clear()
    missing_file = isolated_workspace / "phantom_file.txt"

    # Simulate a tool that claims success but fails to create the physical file on disk
    def _fake_create_file(path: str, content: str = "", overwrite: bool = False) -> dict[str, Any]:
        return {
            "operation": "create_file",
            "path": path,
            "success": True,
        }

    monkeypatch.setattr(filesystem_service, "create_file", _fake_create_file)

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create phantom file",
                tool_name="create_file",
                arguments={"path": str(missing_file), "content": "Never written"},
            )
        ],
    )

    # 1. Initial request halts for confirmation
    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Create phantom_file.txt")
        prompt = await brain.process(req)
        assert "confirm" in prompt.lower()

        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # 2. Confirm execution
    confirm_resp = await brain.process(f"/confirm {action_id}")

    # 3. Post-condition check failed: VerificationEngine reported NOT_VERIFIED
    # Response must report the verification failure cleanly and MUST NOT report success or VERIFIED
    assert "verification failed" in confirm_resp.lower()
    assert "does not exist" in confirm_resp.lower()
    assert "executed successfully" not in confirm_resp.lower()
    assert not missing_file.exists()
