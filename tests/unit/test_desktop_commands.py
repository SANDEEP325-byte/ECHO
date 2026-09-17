from pathlib import Path
import subprocess
from unittest.mock import MagicMock
import pytest

from packages.common.tool_registry import tool_registry
from packages.interfaces.execution import ExecutionResult
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.tool_invocation import ToolInvocation
from services.brain.execution import ExecutionEngine
from services.brain.tool_router import tool_router
from services.brain.verification import VerificationEngine
from services.desktop.commands import (
    CommandErrorCode,
    CommandExecutionPolicy,
    CommandExecutor,
    CommandPolicyError,
)
from services.desktop.policy import DesktopSecurityPolicy
from services.security.risk import RiskClassifier
from services.security.safety_engine import SafetyEngine


@pytest.fixture
def mock_proc_runner():
    """Mock process runner returning standard successful subprocess CompletedProcess."""
    runner = MagicMock()
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = b"mock output\n"
    proc.stderr = b""
    runner.return_value = proc
    return runner


@pytest.fixture
def isolated_command_env(tmp_path: Path, mock_proc_runner):
    """Provides isolated sandbox environment with mock command executor and policy."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    workspace = sandbox / "Workspace"
    workspace.mkdir()

    desktop = sandbox / "Desktop"
    desktop.mkdir()

    documents = sandbox / "Documents"
    documents.mkdir()

    downloads = sandbox / "Downloads"
    downloads.mkdir()

    # Fake trusted Program Files for testing executable discovery
    fake_pf = tmp_path / "ProgramFiles"
    fake_pf.mkdir()

    fake_git_cmd = fake_pf / "Git" / "cmd"
    fake_git_cmd.mkdir(parents=True)
    fake_git_exe = fake_git_cmd / "git.exe"
    fake_git_exe.write_text("dummy git binary")

    fake_py_dir = fake_pf / "Python312"
    fake_py_dir.mkdir(parents=True)
    fake_py_exe = fake_py_dir / "python.exe"
    fake_py_exe.write_text("dummy python binary")

    desktop_policy = DesktopSecurityPolicy(
        authorized_roots=[workspace, desktop, documents, downloads],
        include_default_roots=False,
    )

    cmd_policy = CommandExecutionPolicy(
        desktop_policy=desktop_policy,
        trusted_roots=[fake_pf],
    )

    executor = CommandExecutor(
        policy=cmd_policy,
        process_runner=mock_proc_runner,
        timeout=15.0,
        max_output_bytes=1024,
    )

    return {
        "sandbox": sandbox,
        "workspace": workspace,
        "desktop": desktop,
        "documents": documents,
        "downloads": downloads,
        "fake_pf": fake_pf,
        "fake_git_exe": fake_git_exe,
        "fake_py_exe": fake_py_exe,
        "outside": tmp_path / "outside",
        "desktop_policy": desktop_policy,
        "cmd_policy": cmd_policy,
        "executor": executor,
        "mock_proc_runner": mock_proc_runner,
    }


# ==========================================
# 1. ALLOWED COMMANDS (git & python)
# ==========================================

def test_allowed_git_status(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("git", ["status"], cwd=ws)
    assert res["status"] == "success"
    assert res["command"] == "git"
    assert res["arguments"] == ["status"]
    assert res["exit_code"] == 0
    assert res["verified"] is True
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(ws.resolve())
    assert "status" in args[0]
    assert "--no-pager" in args[0]
    assert "-c" in args[0]
    assert "core.fsmonitor=false" in args[0]


def test_allowed_git_log(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("git", ["log", "--oneline", "-n", "5"], cwd=ws)
    assert res["status"] == "success"
    assert res["command"] == "git"
    assert res["arguments"] == ["log", "--oneline", "-n", "5"]
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert kwargs["shell"] is False
    assert "log" in args[0]
    assert "--no-ext-diff" in args[0]
    assert "--no-textconv" in args[0]


def test_allowed_git_log_negative_count_syntax(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("git", ["log", "-5"], cwd=ws)
    assert res["status"] == "success"
    runner.assert_called_once()


def test_allowed_git_diff(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("git", ["diff", "--stat"], cwd=ws)
    assert res["status"] == "success"
    assert res["command"] == "git"
    assert res["arguments"] == ["diff", "--stat"]
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert kwargs["shell"] is False
    assert "diff" in args[0]
    assert "--no-ext-diff" in args[0]
    assert "--no-textconv" in args[0]


def test_allowed_python_version(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("python", ["--version"], cwd=ws)
    assert res["status"] == "success"
    assert res["command"] == "python"
    assert res["arguments"] == ["--version"]
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert kwargs["shell"] is False
    assert args[0][1:] == ["--version"]


def test_allowed_python_short_version(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("python", ["-V"], cwd=ws)
    assert res["status"] == "success"
    assert res["command"] == "python"
    runner.assert_called_once()


def test_allowed_python_double_v_version(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]
    ws = isolated_command_env["workspace"]

    res = executor.execute_command("python", ["-VV"], cwd=ws)
    assert res["status"] == "success"
    assert res["command"] == "python"
    runner.assert_called_once()


# ==========================================
# 2. GIT CONFIGURATION & HARDENING TESTS
# ==========================================

def test_repo_fsmonitor_hardened_against_config_execution(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    executor.execute_command("git", ["status"])
    runner.assert_called_once()
    argv = runner.call_args[0][0]

    # -c core.fsmonitor=false must be present before the subcommand
    assert "-c" in argv
    assert "core.fsmonitor=false" in argv
    subcmd_index = argv.index("status")
    fsmonitor_index = argv.index("core.fsmonitor=false")
    assert fsmonitor_index < subcmd_index


def test_external_diff_and_textconv_disabled_for_diff(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    executor.execute_command("git", ["diff", "--stat"])
    runner.assert_called_once()
    argv = runner.call_args[0][0]

    # Global -c diff.external= and --no-ext-diff must be present
    assert "diff.external=" in argv
    assert "--no-ext-diff" in argv
    assert "--no-textconv" in argv


def test_pager_disabled_via_no_pager(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    executor.execute_command("git", ["log", "--oneline"])
    runner.assert_called_once()
    argv = runner.call_args[0][0]

    # Must contain --no-pager and core.pager=
    assert "--no-pager" in argv
    assert "core.pager=" in argv


def test_git_hardening_cannot_be_overridden_by_user_arguments(isolated_command_env):
    executor = isolated_command_env["executor"]

    # Trying to re-enable external diff or textconv via user args is blocked by allowlist
    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["diff", "--ext-diff"])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["log", "--paginate"])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


# ==========================================
# 3. GIT STRICT ARGUMENT ALLOWLIST TESTS
# ==========================================

def test_git_status_unknown_flag_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    for bad_flag in ["--find-renames", "--color", "-uall", "--untracked-files"]:
        with pytest.raises(CommandPolicyError) as exc:
            executor.execute_command("git", ["status", bad_flag])
        assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS
        assert "not in the approved allowlist" in str(exc.value)


def test_git_log_unknown_flag_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    for bad_flag in ["--author=alice", "--grep=fix", "--follow", "--since=yesterday"]:
        with pytest.raises(CommandPolicyError) as exc:
            executor.execute_command("git", ["log", bad_flag])
        assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


def test_git_diff_unknown_flag_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    for bad_flag in ["--color-words", "--word-diff", "--ignore-all-space", "--output=foo"]:
        with pytest.raises(CommandPolicyError) as exc:
            executor.execute_command("git", ["diff", bad_flag])
        assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


def test_git_log_invalid_count_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    # Zero count
    with pytest.raises(CommandPolicyError):
        executor.execute_command("git", ["log", "-n", "0"])

    # Negative count
    with pytest.raises(CommandPolicyError):
        executor.execute_command("git", ["log", "-n", "-5"])

    # Non-digit count
    with pytest.raises(CommandPolicyError):
        executor.execute_command("git", ["log", "-n", "abc"])

    # Missing value
    with pytest.raises(CommandPolicyError):
        executor.execute_command("git", ["log", "-n"])

    # Zero via -0
    with pytest.raises(CommandPolicyError):
        executor.execute_command("git", ["log", "-0"])


@pytest.mark.parametrize("dangerous_subcmd", [
    "push",
    "reset",
    "clean",
    "checkout",
    "switch",
    "commit",
    "config",
    "remote",
    "clone",
    "fetch",
    "pull",
    "rebase",
    "merge",
    "branch",
    "tag",
    "stash",
    "rm",
    "mv",
    "init",
])
def test_git_prohibited_subcommands_rejected(isolated_command_env, dangerous_subcmd):
    executor = isolated_command_env["executor"]

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", [dangerous_subcmd])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


# ==========================================
# 4. EXECUTABLE TRUST (TRUSTED-ROOT ALLOWLIST)
# ==========================================

def test_executable_in_downloads_rejected(isolated_command_env):
    policy = isolated_command_env["cmd_policy"]
    downloads = isolated_command_env["downloads"]

    fake_git = downloads / "git.exe"
    fake_git.write_text("evil")

    assert policy._is_in_trusted_root(fake_git) is False


def test_executable_in_desktop_rejected(isolated_command_env):
    policy = isolated_command_env["cmd_policy"]
    desktop = isolated_command_env["desktop"]

    fake_git = desktop / "git.exe"
    fake_git.write_text("evil")

    assert policy._is_in_trusted_root(fake_git) is False


def test_executable_in_workspace_rejected(isolated_command_env):
    policy = isolated_command_env["cmd_policy"]
    workspace = isolated_command_env["workspace"]

    fake_py = workspace / "python.exe"
    fake_py.write_text("evil")

    assert policy._is_in_trusted_root(fake_py) is False


def test_executable_in_appdata_local_programs_rejected(isolated_command_env):
    policy = isolated_command_env["cmd_policy"]
    appdata_prog = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "python.exe"

    assert policy._is_in_trusted_root(appdata_prog) is False


def test_executable_in_arbitrary_tools_dir_rejected(isolated_command_env, tmp_path: Path):
    policy = isolated_command_env["cmd_policy"]
    custom_tools = tmp_path / "tools" / "git.exe"

    assert policy._is_in_trusted_root(custom_tools) is False


def test_executable_outside_trusted_roots_rejected_on_resolve(tmp_path: Path):
    # Policy with strict trusted roots that do NOT contain untrusted binaries
    trusted_dir = tmp_path / "empty_trusted"
    trusted_dir.mkdir()

    policy = CommandExecutionPolicy(trusted_roots=[trusted_dir])
    with pytest.raises(CommandPolicyError) as exc:
        policy.resolve_executable("git")
    assert exc.value.error_code == CommandErrorCode.EXECUTABLE_NOT_TRUSTED


def test_executable_outside_trusted_python_root_rejected(tmp_path: Path):
    trusted_dir = tmp_path / "empty_trusted"
    trusted_dir.mkdir()

    policy = CommandExecutionPolicy(trusted_roots=[trusted_dir])
    with pytest.raises(CommandPolicyError) as exc:
        policy.resolve_executable("python")
    assert exc.value.error_code == CommandErrorCode.EXECUTABLE_NOT_TRUSTED


def test_symlink_resolving_outside_trusted_root_rejected(isolated_command_env, tmp_path: Path):
    policy = isolated_command_env["cmd_policy"]
    fake_pf = isolated_command_env["fake_pf"]

    # Outside malicious binary
    outside_bin = tmp_path / "outside" / "malicious.exe"
    outside_bin.parent.mkdir(parents=True, exist_ok=True)
    outside_bin.write_text("evil")

    # Symlink placed inside trusted root pointing to outside malicious binary
    symlink_in_root = fake_pf / "symlink_evil.exe"
    try:
        symlink_in_root.symlink_to(outside_bin)
        assert policy._is_in_trusted_root(symlink_in_root) is False
    except (OSError, NotImplementedError):
        # On Windows without SeCreateSymbolicLinkPrivilege, test via resolved path simulation
        fake_resolved = MagicMock()
        fake_resolved.resolve.return_value = outside_bin.resolve()
        assert policy._is_in_trusted_root(fake_resolved) is False


def test_shutil_which_outside_trusted_roots_rejected(monkeypatch, tmp_path: Path):
    # If shutil.which returns a binary outside trusted roots, it must NOT be trusted
    untrusted_bin = tmp_path / "custom_tools" / "git.exe"
    untrusted_bin.parent.mkdir(parents=True, exist_ok=True)
    untrusted_bin.write_text("untrusted git")

    monkeypatch.setattr("shutil.which", lambda cmd: str(untrusted_bin))

    trusted_empty = tmp_path / "empty_trusted"
    trusted_empty.mkdir()
    policy = CommandExecutionPolicy(trusted_roots=[trusted_empty])

    with pytest.raises(CommandPolicyError) as exc:
        policy.resolve_executable("git")
    assert exc.value.error_code == CommandErrorCode.EXECUTABLE_NOT_TRUSTED


def test_user_supplied_executable_path_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    for path_str in [r"C:\Program Files\Git\cmd\git.exe", "/bin/sh", r"..\evil.exe"]:
        with pytest.raises(CommandPolicyError) as exc:
            executor.execute_command(path_str)
        assert exc.value.error_code == CommandErrorCode.COMMAND_NOT_ALLOWED


# ==========================================
# 5. ENVIRONMENT SANITIZATION
# ==========================================

def test_inherited_git_env_vars_scrubbed(isolated_command_env, monkeypatch):
    executor = isolated_command_env["executor"]

    # Populate dangerous GIT_* variables in environment
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", r"C:\payload.exe")
    monkeypatch.setenv("GIT_PAGER", r"C:\payload.exe")
    monkeypatch.setenv("GIT_CONFIG", r"C:\fake.gitconfig")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", r"C:\fake.gitconfig")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "evil.exe")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_SSH_COMMAND", "evil_ssh")
    monkeypatch.setenv("GIT_ASKPASS", "evil_askpass")
    monkeypatch.setenv("GIT_EDITOR", "evil_editor")
    monkeypatch.setenv("GIT_EXEC_PATH", r"C:\evil_path")

    clean_env = executor._sanitize_environment()

    assert "GIT_EXTERNAL_DIFF" not in clean_env
    assert "GIT_PAGER" not in clean_env
    assert "GIT_CONFIG" not in clean_env
    assert "GIT_CONFIG_GLOBAL" not in clean_env
    assert "GIT_CONFIG_KEY_0" not in clean_env
    assert "GIT_CONFIG_VALUE_0" not in clean_env
    assert "GIT_CONFIG_COUNT" not in clean_env
    assert "GIT_SSH_COMMAND" not in clean_env
    assert "GIT_ASKPASS" not in clean_env
    assert "GIT_EDITOR" not in clean_env
    assert "GIT_EXEC_PATH" not in clean_env

    # Safe defaults are set
    assert clean_env["GIT_TERMINAL_PROMPT"] == "0"
    assert clean_env["GIT_OPTIONAL_LOCKS"] == "0"


def test_python_injection_vars_scrubbed(isolated_command_env, monkeypatch):
    executor = isolated_command_env["executor"]

    monkeypatch.setenv("PYTHONPATH", "/evil/path")
    monkeypatch.setenv("PYTHONHOME", "/evil/home")
    monkeypatch.setenv("PYTHONSTARTUP", "/evil/startup.py")
    monkeypatch.setenv("PYTHONUSERBASE", "/evil/userbase")
    monkeypatch.setenv("PYTHONINSPECT", "1")
    monkeypatch.setenv("PYTHONBREAKPOINT", "pdb.set_trace")
    monkeypatch.setenv("PYTHONWARNINGS", "ignore")

    clean_env = executor._sanitize_environment()

    for var in [
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONINSPECT",
        "PYTHONBREAKPOINT",
        "PYTHONWARNINGS",
    ]:
        assert var not in clean_env


def test_user_supplied_env_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["status"], env={"FOO": "BAR"})
    assert exc.value.error_code == CommandErrorCode.POLICY_BLOCKED


# ==========================================
# 6. PYTHON RESTRICTIONS
# ==========================================

def test_python_arbitrary_code_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    # -c code execution
    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("python", ["-c", "print('hello')"])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS

    # -m module execution
    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("python", ["-m", "http.server"])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS

    # Script execution
    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("python", ["script.py"])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS

    # No arguments
    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("python", [])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


# ==========================================
# 7. PROHIBITED SHELL INTERPRETERS & METACHA
# ==========================================

@pytest.mark.parametrize("shell_cmd", [
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "bash",
    "bash.exe",
    "sh",
    "sh.exe",
])
def test_shell_interpreters_strictly_rejected(isolated_command_env, shell_cmd):
    executor = isolated_command_env["executor"]

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command(shell_cmd)
    assert exc.value.error_code == CommandErrorCode.COMMAND_NOT_ALLOWED


@pytest.mark.parametrize("bad_arg", [
    "status & whoami",
    "status && calc",
    "status || dir",
    "status | grep foo",
    "status ; rm -rf /",
    "> output.txt",
    "< input.txt",
    "`whoami`",
    "$(whoami)",
    "${USER}",
    "status\nevil",
    "status\revil",
    "status\x00evil",
])
def test_shell_metacharacters_in_arguments_rejected(isolated_command_env, bad_arg):
    executor = isolated_command_env["executor"]

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", [bad_arg])
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


def test_command_string_instead_of_list_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", "status && whoami")
    assert exc.value.error_code == CommandErrorCode.INVALID_ARGUMENTS


# ==========================================
# 8. WORKING DIRECTORY VALIDATION
# ==========================================

def test_cwd_outside_sandbox_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]
    outside = isolated_command_env["outside"]
    outside.mkdir(parents=True, exist_ok=True)

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["status"], cwd=outside)
    assert exc.value.error_code == CommandErrorCode.INVALID_WORKING_DIRECTORY


def test_cwd_path_traversal_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]
    ws = isolated_command_env["workspace"]

    traversal = ws / ".." / "outside_dir"
    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["status"], cwd=traversal)
    assert exc.value.error_code == CommandErrorCode.INVALID_WORKING_DIRECTORY


def test_cwd_unc_path_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["status"], cwd=r"\\remote\share")
    assert exc.value.error_code == CommandErrorCode.INVALID_WORKING_DIRECTORY


def test_cwd_sensitive_path_rejected(isolated_command_env):
    executor = isolated_command_env["executor"]
    ws = isolated_command_env["workspace"]

    ssh_dir = ws / ".ssh"
    ssh_dir.mkdir(exist_ok=True)

    with pytest.raises(CommandPolicyError) as exc:
        executor.execute_command("git", ["status"], cwd=ssh_dir)
    assert exc.value.error_code == CommandErrorCode.INVALID_WORKING_DIRECTORY


# ==========================================
# 9. TIMEOUT, BOUNDED OUTPUT & FAILURES
# ==========================================

def test_command_timeout_handled(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    runner.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=15.0)

    res = executor.execute_command("git", ["status"])
    assert res["status"] == "timeout"
    assert res["timed_out"] is True
    assert res["exit_code"] is None
    assert "timed out" in res["stderr"]
    assert res["verified"] is False


def test_command_output_bounded_and_truncated(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    large_stdout = b"A" * 4000
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = large_stdout
    proc.stderr = b""
    runner.return_value = proc

    res = executor.execute_command("git", ["status"])
    assert res["status"] == "success"
    assert res["truncated"] is True
    assert len(res["stdout"]) <= 1200
    assert "[OUTPUT TRUNCATED" in res["stdout"]


def test_command_nonzero_exit_code_handled(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    proc = MagicMock()
    proc.returncode = 128
    proc.stdout = b""
    proc.stderr = b"fatal: not a git repository\n"
    runner.return_value = proc

    res = executor.execute_command("git", ["status"])
    assert res["status"] == "failed"
    assert res["exit_code"] == 128
    assert "not a git repository" in res["stderr"]
    assert res["verified"] is True


def test_command_process_launch_failure_handled(isolated_command_env):
    executor = isolated_command_env["executor"]
    runner = isolated_command_env["mock_proc_runner"]

    runner.side_effect = OSError("Process spawn failed")

    res = executor.execute_command("git", ["status"])
    assert res["status"] == "failed"
    assert res["exit_code"] is None
    assert "Process execution failed" in res["stderr"]
    assert res["verified"] is False


# ==========================================
# 10. TOOL INTEGRATION & CONFIRMATION PIPELINE
# ==========================================

def test_tool_registry_contains_execute_command():
    tool = tool_registry.get("execute_command")
    assert tool is not None
    assert tool.name == "execute_command"


def test_tool_router_executes_execute_command(isolated_command_env, monkeypatch):
    import services.brain.tools.command_tools as cmd_tools_mod

    executor = isolated_command_env["executor"]
    monkeypatch.setattr(cmd_tools_mod, "command_executor", executor)

    res = tool_router.execute_tool(
        "execute_command",
        command="git",
        arguments=["status"],
    )
    assert res["status"] == "success"
    assert res["command"] == "git"


def test_tool_invocation_validates_execute_command():
    inv = ToolInvocation(
        tool_name="execute_command",
        arguments={"command": "git", "arguments": ["status"]},
    )
    assert inv.validate()[0] is True

    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="execute_command", arguments={})
    assert "requires 'command'" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        ToolInvocation(tool_name="execute_command", arguments={"command": "git & evil"})
    assert "prohibited" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        ToolInvocation(
            tool_name="execute_command",
            arguments={"command": "git", "arguments": "status && dir"},
        )
    assert "list of strings" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        ToolInvocation(
            tool_name="execute_command",
            arguments={"command": "git", "arguments": ["status; rm -rf /"]},
        )
    assert "Forbidden shell metacharacter" in str(exc.value)


def test_safety_engine_and_risk_classifier_for_execute_command():
    classifier = RiskClassifier()
    assert classifier.classify("execute_command") == RiskLevel.SENSITIVE
    assert classifier.classify("run_command") == RiskLevel.SENSITIVE

    safety = SafetyEngine()
    eval_res = safety.evaluate("execute_command", arguments={"command": "git", "arguments": ["status"]})
    assert eval_res.risk_level == RiskLevel.SENSITIVE
    assert eval_res.decision == PermissionDecision.CONFIRM

    eval_dangerous = safety.evaluate(
        "execute_command",
        arguments={"command": "git", "arguments": ["rm -rf"]},
    )
    assert eval_dangerous.risk_level == RiskLevel.CRITICAL
    assert eval_dangerous.decision == PermissionDecision.CONFIRM


def test_execution_engine_requires_confirmation_for_execute_command():
    engine = ExecutionEngine()
    request = Request(user_input="Check git status")
    request.selected_tools = ["execute_command"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Run git status",
                tool_name="execute_command",
                arguments={"command": "git", "arguments": ["status"]},
            )
        ],
    )

    result = engine.execute(request, plan)
    assert result.success is False
    assert result.requires_confirmation is True
    assert result.pending_action is not None
    assert result.pending_action["tool"] == "execute_command"
    assert result.pending_action["arguments"]["command"] == "git"


def test_verification_engine_verifies_command_execution():
    verifier = VerificationEngine()
    request = Request(user_input="Run git status")

    exec_res = ExecutionResult(
        success=True,
        result=[{
            "operation": "execute_command",
            "command": "git",
            "status": "success",
            "exit_code": 0,
            "timed_out": False,
            "verified": True,
        }],
    )
    v_res = verifier.verify(request, exec_res)
    assert v_res.success is True

    timeout_res = ExecutionResult(
        success=True,
        result=[{
            "operation": "execute_command",
            "command": "git",
            "status": "timeout",
            "exit_code": None,
            "timed_out": True,
            "verified": False,
        }],
    )
    v_timeout = verifier.verify(request, timeout_res)
    assert v_timeout.success is False
    assert "timed out" in v_timeout.error
