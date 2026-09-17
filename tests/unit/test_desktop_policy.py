import os
from pathlib import Path
import pytest

from services.desktop.policy import (
    DesktopSecurityPolicy,
    OperationType,
    PolicyCheckResult,
    PolicyErrorCode,
    SecurityPolicyError,
)


@pytest.fixture
def sandbox_roots(tmp_path: Path):
    """Provides isolated temporary sandbox directories."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    desktop = sandbox / "Desktop"
    desktop.mkdir()

    documents = sandbox / "Documents"
    documents.mkdir()

    downloads = sandbox / "Downloads"
    downloads.mkdir()

    workspace = sandbox / "ECHO_Workspace"
    workspace.mkdir()

    return {
        "sandbox": sandbox,
        "desktop": desktop,
        "documents": documents,
        "downloads": downloads,
        "workspace": workspace,
        "roots": [desktop, documents, downloads, workspace],
    }


@pytest.fixture
def policy(sandbox_roots):
    """Creates a DesktopSecurityPolicy with explicit isolated roots."""
    return DesktopSecurityPolicy(
        authorized_roots=sandbox_roots["roots"],
        include_default_roots=False,
    )


# 1. Authorized path accepted
def test_authorized_path_accepted(policy: DesktopSecurityPolicy, sandbox_roots):
    doc_file = sandbox_roots["documents"] / "report.txt"
    doc_file.write_text("hello world")

    result = policy.validate(doc_file, OperationType.READ)
    assert result.allowed is True
    assert result.error_code is None
    assert result.operation == OperationType.READ


# 2. Unauthorized path rejected
def test_unauthorized_path_rejected(policy: DesktopSecurityPolicy, tmp_path: Path):
    unauthorized = tmp_path / "outside_sandbox" / "secret.txt"
    unauthorized.parent.mkdir(parents=True, exist_ok=True)
    unauthorized.write_text("forbidden")

    result = policy.validate(unauthorized, OperationType.READ)
    assert result.allowed is False
    assert result.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX


# 3. ../ traversal rejected
def test_parent_traversal_rejected(policy: DesktopSecurityPolicy, sandbox_roots):
    # Attempt to traverse out of Documents to its parent (which is outside the authorized roots)
    traversal_path = sandbox_roots["documents"] / ".." / "unauthorized.txt"

    result = policy.validate(traversal_path, OperationType.READ)
    assert result.allowed is False
    assert result.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX


# 4. Sibling-prefix attack rejected
def test_sibling_prefix_attack_rejected(policy: DesktopSecurityPolicy, sandbox_roots):
    # Create a sibling directory named Documents-secret next to Documents
    sibling_secret = sandbox_roots["sandbox"] / "Documents-secret"
    sibling_secret.mkdir(exist_ok=True)
    evil_file = sibling_secret / "evil.txt"
    evil_file.write_text("evil")

    result = policy.validate(evil_file, OperationType.READ)
    assert result.allowed is False
    assert result.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX


# 5. Absolute unauthorized path rejected
def test_absolute_unauthorized_path_rejected(policy: DesktopSecurityPolicy):
    abs_path = Path("C:/SomeRandomDirectory/outside.txt")
    result = policy.validate(abs_path, OperationType.READ)
    assert result.allowed is False
    assert result.error_code in (
        PolicyErrorCode.PATH_OUTSIDE_SANDBOX,
        PolicyErrorCode.PROTECTED_LOCATION,
    )


# 6. UNC / network path rejected
def test_unc_path_rejected(policy: DesktopSecurityPolicy):
    unc_path = r"\\server\share\file.txt"
    result = policy.validate(unc_path, OperationType.READ)
    assert result.allowed is False
    assert result.error_code == PolicyErrorCode.UNC_PATH_REJECTED

    # Forward slash UNC
    unc_forward = "//server/share/file.txt"
    result_fwd = policy.validate(unc_forward, OperationType.READ)
    assert result_fwd.allowed is False
    assert result_fwd.error_code == PolicyErrorCode.UNC_PATH_REJECTED


# 7. Protected directory rejected
def test_protected_system_directory_rejected(policy: DesktopSecurityPolicy):
    windows_path = Path(r"C:\Windows\System32\cmd.exe")
    result = policy.validate(windows_path, OperationType.READ)
    assert result.allowed is False
    assert result.error_code == PolicyErrorCode.PROTECTED_LOCATION

    prog_files = Path(r"C:\Program Files\App\secret.dll")
    result_prog = policy.validate(prog_files, OperationType.READ)
    assert result_prog.allowed is False
    assert result_prog.error_code == PolicyErrorCode.PROTECTED_LOCATION

    drive_root = Path("C:\\")
    result_root = policy.validate(drive_root, OperationType.READ)
    assert result_root.allowed is False
    assert result_root.error_code == PolicyErrorCode.PROTECTED_LOCATION


# 8. Protected filename rejected
def test_protected_filename_rejected(policy: DesktopSecurityPolicy, sandbox_roots):
    # .env inside authorized workspace
    env_file = sandbox_roots["workspace"] / ".env"
    result_env = policy.validate(env_file, OperationType.READ)
    assert result_env.allowed is False
    assert result_env.error_code == PolicyErrorCode.SENSITIVE_FILE

    # .env.local
    env_local = sandbox_roots["workspace"] / ".env.local"
    result_local = policy.validate(env_local, OperationType.READ)
    assert result_local.allowed is False
    assert result_local.error_code == PolicyErrorCode.SENSITIVE_FILE

    # .ssh folder or id_rsa
    ssh_file = sandbox_roots["documents"] / ".ssh" / "id_rsa"
    result_ssh = policy.validate(ssh_file, OperationType.READ)
    assert result_ssh.allowed is False
    assert result_ssh.error_code == PolicyErrorCode.SENSITIVE_FILE

    # credentials.json
    creds = sandbox_roots["downloads"] / "credentials.json"
    result_creds = policy.validate(creds, OperationType.READ)
    assert result_creds.allowed is False
    assert result_creds.error_code == PolicyErrorCode.SENSITIVE_FILE

    # private key .pem
    cert_key = sandbox_roots["workspace"] / "private.key"
    result_key = policy.validate(cert_key, OperationType.READ)
    assert result_key.allowed is False
    assert result_key.error_code == PolicyErrorCode.SENSITIVE_FILE


# 9. Symlink escape rejected where Windows permits
def test_symlink_escape_rejected(policy: DesktopSecurityPolicy, sandbox_roots, tmp_path: Path, monkeypatch):
    target_outside = (tmp_path / "outside_target.txt").resolve()
    target_outside.write_text("secret target")

    link_inside = sandbox_roots["documents"] / "link_to_outside.txt"

    try:
        os.symlink(target_outside, link_inside)
        result = policy.validate(link_inside, OperationType.READ)
    except (OSError, NotImplementedError):
        # On Windows environments without Developer Mode/elevated symlink rights,
        # simulate symlink resolution escaping the sandbox via mock
        original_normalize = policy.normalize_path
        def fake_normalize(p):
            if str(p) == str(link_inside):
                return target_outside
            return original_normalize(p)
        monkeypatch.setattr(policy, "normalize_path", fake_normalize)
        result = policy.validate(link_inside, OperationType.READ)

    assert result.allowed is False
    assert result.error_code in (
        PolicyErrorCode.PATH_OUTSIDE_SANDBOX,
        PolicyErrorCode.SYMLINK_ESCAPE,
    )


# 21. Source and destination independently validated
def test_source_and_destination_independently_validated(
    policy: DesktopSecurityPolicy, sandbox_roots, tmp_path: Path
):
    valid_source = sandbox_roots["documents"] / "source.txt"
    valid_source.write_text("content")

    invalid_dest = tmp_path / "outside" / "dest.txt"

    res_src = policy.validate(valid_source, OperationType.READ)
    res_dst = policy.validate(invalid_dest, OperationType.CREATE)

    assert res_src.allowed is True
    assert res_dst.allowed is False
    assert res_dst.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX


# 23. Malformed path handling
def test_malformed_path_handling(policy: DesktopSecurityPolicy):
    # Null byte in path
    result_null = policy.validate("test\x00evil.txt", OperationType.READ)
    assert result_null.allowed is False
    assert result_null.error_code == PolicyErrorCode.INVALID_PATH

    # Empty path
    result_empty = policy.validate("", OperationType.READ)
    assert result_empty.allowed is False
    assert result_empty.error_code == PolicyErrorCode.INVALID_PATH

    # Blank spaces path
    result_blank = policy.validate("   ", OperationType.READ)
    assert result_blank.allowed is False
    assert result_blank.error_code == PolicyErrorCode.INVALID_PATH


# 24. Safe error handling
def test_safe_error_handling_no_secrets_leaked(policy: DesktopSecurityPolicy):
    with pytest.raises(SecurityPolicyError) as exc_info:
        policy.validate_or_raise(r"\\evil_server\share\secrets.txt", OperationType.READ)

    err = exc_info.value
    assert err.error_code == PolicyErrorCode.UNC_PATH_REJECTED
    # Ensure error reason is generic, safe and does not leak internal traces
    assert "Network and UNC paths are not permitted" in err.reason


def test_delete_root_directory_forbidden(policy: DesktopSecurityPolicy, sandbox_roots):
    # Attempting to delete Documents (an authorized root) must be rejected
    result = policy.validate(sandbox_roots["documents"], OperationType.DELETE)
    assert result.allowed is False
    assert result.error_code == PolicyErrorCode.ROOT_DELETION_FORBIDDEN


def test_environment_variable_expansion(sandbox_roots):
    # Test that env vars are expanded during normalization
    os.environ["ECHO_TEST_DIR"] = str(sandbox_roots["documents"])
    policy = DesktopSecurityPolicy(
        authorized_roots=sandbox_roots["roots"],
        include_default_roots=False,
    )

    path_with_env = "%ECHO_TEST_DIR%/notes.txt"
    norm = policy.normalize_path(path_with_env)
    assert norm == (sandbox_roots["documents"] / "notes.txt").resolve()
