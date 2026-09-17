import os
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.pending_action import (
    ActionState,
    ConfirmationResult,
    ConfirmationStatus,
)
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.verification import (
    VerificationDetail,
    VerificationResult,
    VerificationStatus,
)
from services.brain.execution import ExecutionEngine
from services.brain.verification import VerificationEngine
from services.desktop.policy import DesktopSecurityPolicy, OperationType
from services.security.pending_action_manager import PendingActionManager


@pytest.fixture
def sandbox_setup(tmp_path: Path):
    """Sets up an isolated desktop sandbox environment for verification testing."""
    root = tmp_path / "sandbox"
    root.mkdir()

    workspace = root / "workspace"
    workspace.mkdir()

    docs = root / "documents"
    docs.mkdir()

    policy = DesktopSecurityPolicy(
        authorized_roots=[workspace, docs],
        include_default_roots=False,
    )
    engine = VerificationEngine(desktop_policy=policy)

    return {
        "root": root,
        "workspace": workspace,
        "docs": docs,
        "policy": policy,
        "engine": engine,
        "outside": tmp_path / "outside",
    }


# ==========================================
# 1. STRUCTURED VERIFICATION RESULT MODEL
# ==========================================

def test_verification_status_enums():
    assert VerificationStatus.VERIFIED == "verified"
    assert VerificationStatus.NOT_VERIFIED == "not_verified"
    assert VerificationStatus.NOT_APPLICABLE == "not_applicable"
    assert VerificationStatus.VERIFICATION_ERROR == "verification_error"


def test_verification_detail_structure():
    detail = VerificationDetail(
        operation="create_file",
        status=VerificationStatus.VERIFIED,
        message="Created file verified.",
        expected="File exists",
        observed="File exists",
    )
    d = detail.to_dict()
    assert d["operation"] == "create_file"
    assert d["status"] == "verified"
    assert d["message"] == "Created file verified."
    assert d["expected"] == "File exists"
    assert d["observed"] == "File exists"


def test_verification_result_structured_dictionary_non_leaking():
    detail = VerificationDetail(
        operation="create_file",
        status=VerificationStatus.VERIFIED,
        message="File verified safely.",
        expected="Regular file exists",
        observed="Regular file exists",
    )
    result = VerificationResult(
        success=True,
        status=VerificationStatus.VERIFIED,
        result={"path": "safe.txt"},
        details=[detail],
    )
    data = result.to_dict()
    assert data["success"] is True
    assert data["status"] == "verified"
    assert len(data["details"]) == 1
    assert "traceback" not in data
    assert "env" not in data


def test_verification_result_semantic_consistency():
    # If success=False without status, status becomes NOT_VERIFIED
    res = VerificationResult(success=False, error="Failed")
    assert res.status == VerificationStatus.NOT_VERIFIED

    # If status=VERIFICATION_ERROR, it is preserved
    res_err = VerificationResult(
        success=False,
        status=VerificationStatus.VERIFICATION_ERROR,
        error="Security error",
    )
    assert res_err.status == VerificationStatus.VERIFICATION_ERROR

    # If status=NOT_APPLICABLE with success=True, it is preserved
    res_na = VerificationResult(
        success=True,
        status=VerificationStatus.NOT_APPLICABLE,
        result="some data",
    )
    assert res_na.status == VerificationStatus.NOT_APPLICABLE
    assert res_na.success is True


# ==========================================
# 2. FILESYSTEM POST-CONDITION VERIFICATION
# ==========================================

def test_create_file_verified(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    test_file = ws / "test.txt"
    test_file.write_text("hello", encoding="utf-8")

    req = Request(user_input="Create file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": str(test_file), "status": "created"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED
    assert len(v_res.details) == 1
    assert v_res.details[0].status == VerificationStatus.VERIFIED


def test_create_file_not_verified_when_missing(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    missing_file = ws / "missing.txt"

    req = Request(user_input="Create file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": str(missing_file), "status": "created"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "does not exist" in v_res.error
    assert req.status == RequestStatus.FAILED


def test_create_file_not_verified_when_target_is_directory(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    sub_dir = ws / "not_a_file"
    sub_dir.mkdir()

    req = Request(user_input="Create file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": str(sub_dir), "status": "created"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "not a regular file" in v_res.error


def test_create_folder_verified(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    new_folder = ws / "new_dir"
    new_folder.mkdir()

    req = Request(user_input="Create folder")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_folder", "path": str(new_folder), "status": "created"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


def test_create_folder_not_verified_when_missing(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    missing_folder = ws / "missing_folder"

    req = Request(user_input="Create folder")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_folder", "path": str(missing_folder), "status": "created"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "does not exist" in v_res.error


def test_copy_file_verified(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    src = ws / "src.txt"
    src.write_text("data")
    dst = ws / "dst.txt"
    dst.write_text("data")

    req = Request(user_input="Copy file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "copy_file", "source": str(src), "destination": str(dst)},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


def test_copy_file_not_verified_when_destination_missing(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    src = ws / "src.txt"
    src.write_text("data")
    dst = ws / "missing_dst.txt"

    req = Request(user_input="Copy file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "copy_file", "source": str(src), "destination": str(dst)},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "copied destination" in v_res.error


def test_copy_file_not_verified_when_source_vanished(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    src = ws / "vanished_src.txt"
    dst = ws / "dst.txt"
    dst.write_text("data")

    req = Request(user_input="Copy file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "copy_file", "source": str(src), "destination": str(dst)},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "source file" in v_res.error


def test_rename_and_move_file_verified(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    old_file = ws / "old.txt"
    new_file = ws / "new.txt"
    new_file.write_text("content")

    req = Request(user_input="Rename file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "rename_file", "source": str(old_file), "destination": str(new_file)},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


def test_rename_file_not_verified_when_source_still_exists(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    old_file = ws / "old_remain.txt"
    old_file.write_text("content")
    new_file = ws / "new_path.txt"
    new_file.write_text("content")

    req = Request(user_input="Rename file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "rename_file", "source": str(old_file), "destination": str(new_file)},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "still exists" in v_res.error


def test_delete_file_verified(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    deleted = ws / "deleted.txt"

    req = Request(user_input="Delete file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "delete_file", "path": str(deleted), "status": "deleted"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


def test_delete_file_not_verified_when_file_still_present(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    not_deleted = ws / "survived.txt"
    not_deleted.write_text("still alive")

    req = Request(user_input="Delete file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "delete_file", "path": str(not_deleted), "status": "deleted"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "still exists" in v_res.error


def test_read_and_list_operations_not_applicable(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]

    req = Request(user_input="Read file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "read_file", "path": str(ws / "sample.txt")},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.NOT_APPLICABLE
    assert "read-only" in v_res.details[0].message.lower()


# ==========================================
# 3. LAUNCH VERIFICATION SEMANTICS
# ==========================================

def test_open_file_verified_dispatch_with_unverified_gui(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    doc = ws / "notes.txt"
    doc.write_text("notes")

    req = Request(user_input="Open file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "open_file", "path": str(doc), "status": "opened", "verified": True},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED
    # Explicitly mentions application window lifecycle is not verified
    assert "window lifecycle is not verified" in v_res.details[0].message.lower()


def test_open_file_not_verified_when_file_missing(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    doc = ws / "missing_notes.txt"

    req = Request(user_input="Open file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "open_file", "path": str(doc), "status": "opened", "verified": True},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "does not exist" in v_res.error


def test_open_folder_verified_dispatch_with_unverified_gui(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    sub_dir = ws / "my_folder"
    sub_dir.mkdir()

    req = Request(user_input="Open folder")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "open_folder", "path": str(sub_dir), "status": "opened", "verified": True},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED
    assert "window lifecycle is not verified" in v_res.details[0].message.lower()


def test_open_application_marked_not_applicable_for_gui(sandbox_setup):
    engine = sandbox_setup["engine"]

    # Allowlisted app in trusted system directory
    system_root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    notepad_path = system_root / "notepad.exe"
    if not notepad_path.exists():
        notepad_path = system_root / "System32" / "notepad.exe"

    req = Request(user_input="Open notepad")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "open_application",
            "application": "notepad",
            "path": str(notepad_path),
            "status": "launched",
            "verified": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    # Crucial Requirement 5: NOT_APPLICABLE for process/GUI state
    assert v_res.status == VerificationStatus.NOT_APPLICABLE
    assert "not applicable without unsafe inspection" in v_res.details[0].message


def test_open_application_fails_if_untrusted_executable(sandbox_setup):
    engine = sandbox_setup["engine"]
    fake_exe = sandbox_setup["workspace"] / "malicious.exe"
    fake_exe.write_text("not real")

    req = Request(user_input="Open fake")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "open_application",
            "application": "malicious",
            "path": str(fake_exe),
            "status": "launched",
            "verified": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR
    assert "outside trusted system directory" in v_res.error


# ==========================================
# 4. COMMAND VERIFICATION
# ==========================================

def test_command_verification_success_on_exit_code_zero(sandbox_setup):
    engine = sandbox_setup["engine"]

    req = Request(user_input="Git status")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "execute_command",
            "command": "git",
            "arguments": ["status", "--short"],
            "exit_code": 0,
            "status": "success",
            "timed_out": False,
            "verified": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED
    assert v_res.details[0].observed == "Command executed successfully (exit code 0, bounded output)"


def test_command_verification_not_verified_on_non_zero_exit(sandbox_setup):
    engine = sandbox_setup["engine"]

    req = Request(user_input="Git status")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "execute_command",
            "command": "git",
            "arguments": ["status"],
            "exit_code": 128,
            "status": "failed",
            "timed_out": False,
            "verified": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "non-zero exit code 128" in v_res.error


def test_command_verification_not_verified_on_timeout(sandbox_setup):
    engine = sandbox_setup["engine"]

    req = Request(user_input="Git status")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "execute_command",
            "command": "git",
            "exit_code": None,
            "status": "timeout",
            "timed_out": True,
            "verified": False,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED
    assert "timed out" in v_res.error


# ==========================================
# 5. SECURITY & SANDBOX BOUNDARIES
# ==========================================

def test_verification_rejects_path_outside_sandbox(sandbox_setup):
    engine = sandbox_setup["engine"]
    outside = sandbox_setup["outside"] / "escaped.txt"

    req = Request(user_input="Check file")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": str(outside), "status": "created"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR
    assert "outside the authorized desktop sandbox" in v_res.error


def test_verification_rejects_unc_path(sandbox_setup):
    engine = sandbox_setup["engine"]

    req = Request(user_input="Check UNC")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": r"\\attacker\share\file.txt"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR
    assert "unc" in v_res.error.lower()


def test_verification_rejects_path_with_null_bytes(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]

    req = Request(user_input="Check null byte")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": f"{ws}/file\x00.txt"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR
    assert "null byte" in v_res.error.lower()


def test_verification_rejects_sensitive_files(sandbox_setup):
    engine = sandbox_setup["engine"]
    ws = sandbox_setup["workspace"]
    env_file = ws / ".env"

    req = Request(user_input="Check .env")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": str(env_file)},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR
    assert "credentials, secrets, or environment" in v_res.error.lower()


def test_verification_rejects_protected_system_locations(sandbox_setup):
    engine = sandbox_setup["engine"]

    req = Request(user_input="Check system32")
    exec_res = ExecutionResult(
        success=True,
        result={"operation": "create_file", "path": r"C:\Windows\System32\malicious.dll"},
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR
    assert "strictly prohibited" in v_res.error.lower()


# ==========================================
# 6. EXECUTION ENGINE INTEGRATION & RESUME
# ==========================================

def test_resume_action_success_with_verified_postcondition(sandbox_setup):
    ws = sandbox_setup["workspace"]
    test_file = ws / "to_delete.txt"
    # Ensure file does NOT exist, so delete_file post-condition verification succeeds
    if test_file.exists():
        test_file.unlink()

    mock_router = MagicMock()
    mock_router.execute_tool.return_value = {
        "operation": "delete_file",
        "path": str(test_file),
        "status": "deleted",
        "verified": True,
    }

    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = MagicMock(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
    )

    mgr = PendingActionManager()
    engine = ExecutionEngine(
        router=mock_router,
        safety_engine=mock_safety,
        pending_action_manager=mgr,
        verification_engine=sandbox_setup["engine"],
    )

    action = mgr.create_pending_action(
        tool_name="delete_file",
        arguments={"path": str(test_file)},
        risk_level=RiskLevel.SENSITIVE,
    )

    res = engine.resume_pending_action(action.action_id)
    assert res.success is True
    assert res.status == ConfirmationStatus.CONFIRMED
    assert res.verification is not None
    assert res.verification.status == VerificationStatus.VERIFIED
    assert action.state == ActionState.EXECUTED


def test_resume_action_distinguishes_execution_success_from_verification_failure(sandbox_setup):
    ws = sandbox_setup["workspace"]
    undeleted_file = ws / "still_here.txt"
    undeleted_file.write_text("data")  # File remains, so delete verification will fail!

    mock_router = MagicMock()
    mock_router.execute_tool.return_value = {
        "operation": "delete_file",
        "path": str(undeleted_file),
        "status": "deleted",
        "verified": True,
    }

    mock_safety = MagicMock()
    mock_safety.evaluate.return_value = MagicMock(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
    )

    mgr = PendingActionManager()
    engine = ExecutionEngine(
        router=mock_router,
        safety_engine=mock_safety,
        pending_action_manager=mgr,
        verification_engine=sandbox_setup["engine"],
    )

    action = mgr.create_pending_action(
        tool_name="delete_file",
        arguments={"path": str(undeleted_file)},
        risk_level=RiskLevel.SENSITIVE,
    )

    res = engine.resume_pending_action(action.action_id)
    # Execution succeeded (result is preserved!)
    assert res.result is not None
    assert res.status == ConfirmationStatus.CONFIRMED
    # But overall verification failed!
    assert res.success is False
    assert res.verification is not None
    assert res.verification.status == VerificationStatus.NOT_VERIFIED
    assert "still exists" in res.error

    # Replay is still blocked because the action was already claimed and executed!
    replay_res = engine.resume_pending_action(action.action_id)
    assert replay_res.success is False
    assert replay_res.status == ConfirmationStatus.ALREADY_PROCESSED
