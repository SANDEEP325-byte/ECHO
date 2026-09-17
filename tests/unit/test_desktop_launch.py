import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.tool_invocation import ToolInvocation
from services.brain.execution import ExecutionEngine
from services.brain.tool_selector import ToolSelector
from services.brain.verification import VerificationEngine
from services.desktop.app_launcher import DesktopAppLauncher
from services.desktop.filesystem import FilesystemService
from services.desktop.policy import (
    DesktopSecurityPolicy,
    PolicyErrorCode,
    SecurityPolicyError,
)
from services.security.risk import RiskClassifier
from services.security.safety_engine import SafetyEngine


@pytest.fixture
def mock_launcher():
    """Mock OS launch function so no real windows or processes are created."""
    return MagicMock()


@pytest.fixture
def isolated_desktop_env(tmp_path: Path, mock_launcher):
    """Provides isolated sandbox environment with mocked OS launcher."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    desktop = sandbox / "Desktop"
    desktop.mkdir()

    documents = sandbox / "Documents"
    documents.mkdir()

    downloads = sandbox / "Downloads"
    downloads.mkdir()

    workspace = sandbox / "Workspace"
    workspace.mkdir()

    policy = DesktopSecurityPolicy(
        authorized_roots=[desktop, documents, downloads, workspace],
        include_default_roots=False,
    )

    fs_service = FilesystemService(policy=policy, os_launcher=mock_launcher)
    app_launcher = DesktopAppLauncher(os_launcher=mock_launcher)

    return {
        "sandbox": sandbox,
        "desktop": desktop,
        "documents": documents,
        "downloads": downloads,
        "workspace": workspace,
        "policy": policy,
        "fs_service": fs_service,
        "app_launcher": app_launcher,
        "mock_launcher": mock_launcher,
        "outside": tmp_path / "outside",
    }


# ==========================================
# OPEN_FILE TESTS
# ==========================================

def test_open_authorized_file(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]
    mock = isolated_desktop_env["mock_launcher"]

    test_file = docs / "notes.txt"
    test_file.write_text("my notes", encoding="utf-8")

    res = fs.open_file(test_file)
    assert res["status"] == "opened"
    assert res["verified"] is True
    assert res["path"] == str(test_file.resolve())
    mock.assert_called_once_with(str(test_file.resolve()))


def test_open_unauthorized_file_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    outside = isolated_desktop_env["outside"]
    outside.mkdir(parents=True, exist_ok=True)

    unauthorized_file = outside / "secret.txt"
    unauthorized_file.write_text("confidential")

    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_file(unauthorized_file)

    assert exc_info.value.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_file_traversal_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]

    traversal_target = docs / ".." / "outside_target.txt"

    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_file(traversal_target)

    assert exc_info.value.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_file_unc_path_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    unc = r"\\remote\share\file.txt"

    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_file(unc)

    assert exc_info.value.error_code == PolicyErrorCode.UNC_PATH_REJECTED
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_file_protected_sensitive_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    workspace = isolated_desktop_env["workspace"]

    # .env file
    env_file = workspace / ".env"
    env_file.write_text("API_KEY=xyz")

    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_file(env_file)

    assert exc_info.value.error_code == PolicyErrorCode.SENSITIVE_FILE
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_file_rejects_executable_and_scripts(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    workspace = isolated_desktop_env["workspace"]

    for ext in [".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi"]:
        script_file = workspace / f"malicious{ext}"
        script_file.write_text("echo evil")

        with pytest.raises(SecurityPolicyError) as exc_info:
            fs.open_file(script_file)

        assert exc_info.value.error_code == PolicyErrorCode.SENSITIVE_FILE
        assert "executable, batch, or script" in exc_info.value.reason.lower()

    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_file_nonexistent_fails(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]

    missing = docs / "does_not_exist.txt"
    with pytest.raises(FileNotFoundError):
        fs.open_file(missing)

    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_file_directory_passed_fails(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]

    folder = docs / "subfolder"
    folder.mkdir()

    with pytest.raises(IsADirectoryError):
        fs.open_file(folder)

    isolated_desktop_env["mock_launcher"].assert_not_called()


# ==========================================
# OPEN_FOLDER TESTS
# ==========================================

def test_open_authorized_folder(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]
    mock = isolated_desktop_env["mock_launcher"]

    subfolder = docs / "projects"
    subfolder.mkdir()

    res = fs.open_folder(subfolder)
    assert res["status"] == "opened"
    assert res["verified"] is True
    assert res["path"] == str(subfolder.resolve())
    mock.assert_called_once_with(str(subfolder.resolve()))


def test_open_unauthorized_folder_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    outside = isolated_desktop_env["outside"]
    outside.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_folder(outside)

    assert exc_info.value.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_folder_traversal_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]

    traversal = docs / ".." / "escaped_folder"
    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_folder(traversal)

    assert exc_info.value.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_folder_protected_system_rejected(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    sys_dir = Path(r"C:\Windows\System32")

    with pytest.raises(SecurityPolicyError) as exc_info:
        fs.open_folder(sys_dir)

    assert exc_info.value.error_code == PolicyErrorCode.PROTECTED_LOCATION
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_folder_nonexistent_fails(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]

    missing = docs / "ghost_folder"
    with pytest.raises(FileNotFoundError):
        fs.open_folder(missing)

    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_folder_file_passed_fails(isolated_desktop_env):
    fs = isolated_desktop_env["fs_service"]
    docs = isolated_desktop_env["documents"]

    regular_file = docs / "item.txt"
    regular_file.write_text("data")

    with pytest.raises(NotADirectoryError):
        fs.open_folder(regular_file)

    isolated_desktop_env["mock_launcher"].assert_not_called()


# ==========================================
# OPEN_APPLICATION TESTS
# ==========================================

def test_open_allowed_application(isolated_desktop_env):
    launcher = isolated_desktop_env["app_launcher"]
    mock = isolated_desktop_env["mock_launcher"]

    # Notepad is standard on Windows
    res = launcher.launch_application("notepad")
    assert res["status"] == "launched"
    assert res["verified"] is True
    assert res["application"] == "notepad"
    assert "notepad.exe" in res["path"].lower()
    mock.assert_called_once()


def test_open_allowed_application_alias(isolated_desktop_env):
    launcher = isolated_desktop_env["app_launcher"]
    mock = isolated_desktop_env["mock_launcher"]

    # "calc" aliases to "calculator"
    res = launcher.launch_application("calc")
    assert res["status"] == "launched"
    assert res["application"] == "calculator"
    mock.assert_called_once()


def test_open_unknown_application_fails_closed(isolated_desktop_env):
    launcher = isolated_desktop_env["app_launcher"]

    with pytest.raises(ValueError) as exc_info:
        launcher.launch_application("unknown_malicious_app")

    assert "not in the approved application allowlist" in str(exc_info.value)
    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_application_rejects_arbitrary_executable_paths(isolated_desktop_env):
    launcher = isolated_desktop_env["app_launcher"]

    for dangerous_path in [
        r"C:\Windows\System32\cmd.exe",
        r"C:\Program Files\App\evil.exe",
        r"/bin/sh",
        r"..\evil.exe",
    ]:
        with pytest.raises(ValueError) as exc_info:
            launcher.launch_application(dangerous_path)

        assert "prohibited" in str(exc_info.value).lower() or "not in the approved" in str(exc_info.value).lower()

    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_application_rejects_scripts(isolated_desktop_env):
    launcher = isolated_desktop_env["app_launcher"]

    for script in ["test.bat", "run.ps1", "script.vbs", "app.py"]:
        with pytest.raises(ValueError) as exc_info:
            launcher.launch_application(script)

        assert "prohibited" in str(exc_info.value).lower()

    isolated_desktop_env["mock_launcher"].assert_not_called()


def test_open_application_malformed_arguments(isolated_desktop_env):
    launcher = isolated_desktop_env["app_launcher"]

    with pytest.raises(ValueError):
        launcher.launch_application("")

    with pytest.raises(ValueError):
        launcher.launch_application("   ")

    with pytest.raises(ValueError):
        launcher.launch_application("notepad\x00evil")


def test_open_application_missing_executable_fails_closed(mock_launcher, tmp_path: Path):
    # Launcher where candidate doesn't exist
    fake_app_launcher = DesktopAppLauncher(os_launcher=mock_launcher)
    fake_app_launcher._allowlist["ghost_app"] = {
        "description": "App that is allowlisted but missing on disk",
        "candidates": [tmp_path / "nonexistent" / "ghost.exe"],
    }

    with pytest.raises(FileNotFoundError) as exc_info:
        fake_app_launcher.launch_application("ghost_app")

    assert "was not found" in str(exc_info.value)
    mock_launcher.assert_not_called()


# ==========================================
# PIPELINE & INTEGRATION TESTS
# ==========================================

def test_tool_selector_creates_invocations_for_launch_tools():
    selector = ToolSelector()

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Open document",
                tool_name="open_file",
                arguments={"path": "C:/safe/doc.txt"},
            ),
            PlanStep(
                step_number=2,
                description="Open folder",
                tool_name="open_folder",
                arguments={"path": "C:/safe/folder"},
            ),
            PlanStep(
                step_number=3,
                description="Launch calculator",
                tool_name="open_application",
                arguments={"application_name": "calculator"},
            ),
        ],
    )

    invocations = selector.select_invocations(plan)
    assert len(invocations) == 3
    assert invocations[0].tool_name == "open_file"
    assert invocations[0].arguments == {"path": "C:/safe/doc.txt"}
    assert invocations[1].tool_name == "open_folder"
    assert invocations[1].arguments == {"path": "C:/safe/folder"}
    assert invocations[2].tool_name == "open_application"
    assert invocations[2].arguments == {"application_name": "calculator"}


def test_tool_invocation_validates_launch_parameters():
    # open_file requires path
    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="open_file", arguments={})
    assert "requires 'path'" in str(exc.value)

    # open_folder requires path
    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="open_folder", arguments={})
    assert "requires 'path'" in str(exc.value)

    # open_application requires application_name
    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="open_application", arguments={})
    assert "requires 'application_name'" in str(exc.value)

    # open_application rejects paths and executable extensions
    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="open_application", arguments={"application_name": "C:/cmd.exe"})
    assert "paths and special characters are prohibited" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="open_application", arguments={"application_name": "script.bat"})
    assert "extensions are prohibited" in str(exc.value)


def test_safety_engine_evaluates_launch_tools():
    safety = SafetyEngine()

    res_file = safety.evaluate("open_file", arguments={"path": "notes.txt"})
    assert res_file.risk_level == RiskLevel.SAFE
    assert res_file.decision == PermissionDecision.ALLOW

    res_folder = safety.evaluate("open_folder", arguments={"path": "docs"})
    assert res_folder.risk_level == RiskLevel.SAFE
    assert res_folder.decision == PermissionDecision.ALLOW

    res_app = safety.evaluate("open_application", arguments={"application_name": "notepad"})
    assert res_app.risk_level == RiskLevel.MODERATE
    assert res_app.decision == PermissionDecision.ALLOW

    # Dangerous payload triggers escalation
    res_dangerous = safety.evaluate(
        "open_application",
        arguments={"application_name": "notepad", "extra": "rm -rf /"},
    )
    assert res_dangerous.risk_level == RiskLevel.CRITICAL
    assert res_dangerous.decision == PermissionDecision.CONFIRM


def test_execution_engine_executes_launch_tools(isolated_desktop_env, monkeypatch):
    import services.brain.tools.launch_tools as launch_tools_mod

    fs = isolated_desktop_env["fs_service"]
    app = isolated_desktop_env["app_launcher"]
    docs = isolated_desktop_env["documents"]

    monkeypatch.setattr(launch_tools_mod, "filesystem_service", fs)
    monkeypatch.setattr(launch_tools_mod, "desktop_app_launcher", app)

    doc_file = docs / "presentation.pdf"
    doc_file.write_text("pdf dummy content")

    engine = ExecutionEngine()
    request = Request(user_input="Open presentation and launch notepad")
    request.selected_tools = ["open_file", "open_application"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Open pdf",
                tool_name="open_file",
                arguments={"path": str(doc_file)},
            ),
            PlanStep(
                step_number=2,
                description="Launch notepad",
                tool_name="open_application",
                arguments={"application_name": "notepad"},
            ),
        ],
    )

    result = engine.execute(request, plan)
    assert result.success is True
    assert len(result.result) == 2
    assert result.result[0]["operation"] == "open_file"
    assert result.result[1]["operation"] == "open_application"
    assert isolated_desktop_env["mock_launcher"].call_count == 2


def test_verification_engine_verifies_launch_operations(tmp_path: Path):
    verifier = VerificationEngine()
    target_file = tmp_path / "view.txt"
    target_file.write_text("hello")

    target_folder = tmp_path / "folder"
    target_folder.mkdir()

    request = Request(user_input="Launch test")
    exec_res = ExecutionResult(
        success=True,
        result=[
            {"operation": "open_file", "path": str(target_file), "status": "opened", "verified": True},
            {"operation": "open_folder", "path": str(target_folder), "status": "opened", "verified": True},
        ],
    )

    v_res = verifier.verify(request, exec_res)
    assert v_res.success is True

    # If target file disappeared before verification -> fails
    target_file.unlink()
    v_res_fail = verifier.verify(request, exec_res)
    assert v_res_fail.success is False
    assert "Verification failed" in v_res_fail.error
