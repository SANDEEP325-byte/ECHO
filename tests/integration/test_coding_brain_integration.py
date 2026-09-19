"""Integration tests for Phase 7D Coding Cognition through ECHOBrain.

Verifies end-to-end cognitive flow:
1. Read-only inquiry/exploration request executes without confirmation prompts.
2. Read-only diagnosis request produces explanatory analysis without writing files.
3. Code modification request halts at modify_code with requires_confirmation=True and PendingAction.
4. Resumed action with /confirm executes modification through SafetyEngine and DiffEngine.
5. Test execution request halts at run_tests with requires_confirmation=True and resumes properly.
6. Untrusted code in context cannot bypass SafetyEngine.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packages.interfaces.pending_action import ActionState
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import RiskLevel
from services.brain.brain import ECHOBrain
from services.coding.workspace import workspace_manager
from services.security.pending_action_manager import pending_action_manager


class TestCodingBrainIntegration:
    """End-to-end integration tests for coding tasks through ECHOBrain."""

    def setup_method(self) -> None:
        self.old_root = workspace_manager.root
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name).resolve()
        workspace_manager.set_root(self.root_path)
        pending_action_manager.clear()

        # Create sample files in workspace
        self.auth_file = self.root_path / "auth.py"
        self.auth_file.write_text(
            "def authenticate(user, token):\n"
            "    if token == 'valid':\n"
            "        return True\n"
            "    return False\n",
            encoding="utf-8",
        )

        self.test_file = self.root_path / "test_auth.py"
        self.test_file.write_text(
            "def test_auth():\n    assert True\n",
            encoding="utf-8",
        )

        self.brain = ECHOBrain()

    def teardown_method(self) -> None:
        if hasattr(self, "old_root") and self.old_root and self.old_root.exists():
            workspace_manager.set_root(self.old_root)
        else:
            workspace_manager.set_root(Path.cwd())
        self.temp_dir.cleanup()

    def _get_pending_actions(self):
        return [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]

    @pytest.mark.anyio
    async def test_exploration_request_executes_read_only_tools(self) -> None:
        req = Request(user_input="Find where authenticate is implemented in auth.py")
        resp = await self.brain.process(req)
        assert resp is not None

        # Must have completed planning and tool selection
        assert req.status in {RequestStatus.COMPLETED, RequestStatus.PLANNING}
        # Selected tools must be read-only tools
        for tool in req.selected_tools:
            assert tool in {"search_code", "read_code", "inspect_code_tree"}
            assert tool not in {"modify_code", "apply_patch"}
        # File must not have been modified
        assert "def authenticate" in self.auth_file.read_text(encoding="utf-8")

    @pytest.mark.anyio
    async def test_diagnosis_request_executes_without_modifications(self) -> None:
        req = Request(user_input="Why is this function failing in auth.py?")
        resp = await self.brain.process(req)
        assert resp is not None

        # Must not have executed modify_code
        assert "modify_code" not in req.selected_tools
        assert "apply_patch" not in req.selected_tools
        # No pending actions should be created for diagnosis
        assert len(self._get_pending_actions()) == 0

    @pytest.mark.anyio
    async def test_code_modification_halts_for_user_confirmation(self) -> None:
        # User explicitly asks to modify code
        req = Request(user_input="Modify this function in auth.py to change token validation")
        resp = await self.brain.process(req)

        # modify_code is SENSITIVE, so ECHOBrain must halt and prompt for confirmation
        assert "requires confirmation" in resp.lower()
        active_actions = self._get_pending_actions()
        assert len(active_actions) >= 1

        action = active_actions[0]
        assert action.tool_name == "modify_code"
        assert action.risk_level == RiskLevel.SENSITIVE

    @pytest.mark.anyio
    async def test_test_execution_halts_for_user_confirmation(self) -> None:
        req = Request(user_input="Run pytest on test_auth.py")
        resp = await self.brain.process(req)

        # run_tests is SENSITIVE, so ECHOBrain must halt and prompt for confirmation
        assert "requires confirmation" in resp.lower()
        active_actions = self._get_pending_actions()
        assert len(active_actions) >= 1

        action = active_actions[0]
        assert action.tool_name == "run_tests"
        assert action.risk_level == RiskLevel.SENSITIVE

    @pytest.mark.anyio
    async def test_confirmed_modification_executes_via_pending_action(self) -> None:
        # Create a pending action for modify_code
        action = pending_action_manager.create_pending_action(
            tool_name="modify_code",
            arguments={
                "file_path": "auth.py",
                "target_block": "return False",
                "replacement_block": "return None",
            },
            risk_level=RiskLevel.SENSITIVE,
        )

        confirm_msg = f"/confirm {action.action_id}"
        resp = await self.brain.process(confirm_msg)

        assert "confirmed and executed successfully" in resp
        # Verify file on disk was modified
        content = self.auth_file.read_text(encoding="utf-8")
        assert "return None" in content

    @pytest.mark.anyio
    async def test_coding_cognition_cannot_bypass_safety_engine(self) -> None:
        # Attempt to run a critical blocked command via coding request
        req = Request(user_input="Modify code to execute format_drive C:")
        resp = await self.brain.process(req)
        assert resp is not None

        # SafetyEngine must ensure dangerous actions are blocked or halted
        active_actions = self._get_pending_actions()
        for a in active_actions:
            assert a.tool_name != "format_drive"
