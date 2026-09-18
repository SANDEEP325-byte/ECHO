"""Unit tests for ECHO Coding Workspace Manager and Security (Phase 7A)."""

from pathlib import Path

import pytest

from services.coding.workspace import (
    CodingWorkspace,
    GitIgnoreMatcher,
    WorkspaceError,
)
from services.desktop.policy import PolicyErrorCode


class TestGitIgnoreMatcher:
    """Tests for deterministic standard-library .gitignore rule matcher."""

    def test_default_excluded_directories(self, tmp_path: Path) -> None:
        matcher = GitIgnoreMatcher(tmp_path)
        assert matcher.is_ignored(tmp_path / ".git", is_dir=True) is True
        assert matcher.is_ignored(tmp_path / ".venv", is_dir=True) is True
        assert matcher.is_ignored(tmp_path / "venv", is_dir=True) is True
        assert matcher.is_ignored(tmp_path / "__pycache__", is_dir=True) is True
        assert matcher.is_ignored(tmp_path / "node_modules", is_dir=True) is True
        assert matcher.is_ignored(tmp_path / "src" / "__pycache__", is_dir=True) is True

    def test_gitignore_file_rules(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "# Comment line\n\n*.log\nbuild/\n/root_only.txt\n!important.log\n",
            encoding="utf-8",
        )
        matcher = GitIgnoreMatcher(tmp_path)

        assert matcher.is_ignored(tmp_path / "test.log", is_dir=False) is True
        assert matcher.is_ignored(tmp_path / "important.log", is_dir=False) is False
        assert matcher.is_ignored(tmp_path / "build", is_dir=True) is True
        assert matcher.is_ignored(tmp_path / "root_only.txt", is_dir=False) is True
        assert matcher.is_ignored(tmp_path / "src" / "normal.py", is_dir=False) is False


class TestCodingWorkspace:
    """Tests for CodingWorkspace containment, boundary, and shielding."""

    def test_set_root_valid_directory(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        assert ws.root == tmp_path.resolve()

    def test_set_root_nonexistent_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        ws = CodingWorkspace()
        with pytest.raises(WorkspaceError) as exc_info:
            ws.set_root(nonexistent)
        assert exc_info.value.error_code == PolicyErrorCode.INVALID_PATH

    def test_set_root_file_rejected(self, tmp_path: Path) -> None:
        sample_file = tmp_path / "file.txt"
        sample_file.write_text("content", encoding="utf-8")
        ws = CodingWorkspace()
        with pytest.raises(WorkspaceError) as exc_info:
            ws.set_root(sample_file)
        assert exc_info.value.error_code == PolicyErrorCode.INVALID_PATH

    def test_validate_path_normal_within_workspace(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('hello')", encoding="utf-8")

        resolved = ws.validate_path("src/main.py", must_exist=True)
        assert resolved == target.resolve()

    def test_validate_path_traversal_escape_rejected(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path("../outside.py")
        assert exc_info.value.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX

    def test_validate_path_null_byte_rejected(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path("src/bad\x00file.py")
        assert exc_info.value.error_code == PolicyErrorCode.INVALID_PATH

    def test_validate_path_unc_path_rejected(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path(r"\\evil_server\share\file.py")
        assert exc_info.value.error_code == PolicyErrorCode.UNC_PATH_REJECTED

    def test_validate_path_sensitive_dir_rejected(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        git_dir = tmp_path / ".git" / "config"
        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path(git_dir)
        assert exc_info.value.error_code == PolicyErrorCode.PROTECTED_LOCATION

    def test_validate_path_sensitive_files_rejected(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        sensitive_files = [
            ".env",
            ".env.local",
            "credentials.json",
            "secrets.json",
            "id_rsa",
            "id_ed25519",
        ]
        for name in sensitive_files:
            file_path = tmp_path / name
            file_path.write_text("secret=123", encoding="utf-8")
            with pytest.raises(WorkspaceError) as exc_info:
                ws.validate_path(name)
            assert exc_info.value.error_code == PolicyErrorCode.SENSITIVE_FILE

    def test_validate_path_sensitive_extensions_rejected(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        key_file = tmp_path / "server.key"
        pem_file = tmp_path / "cert.pem"
        key_file.write_text("key content", encoding="utf-8")
        pem_file.write_text("pem content", encoding="utf-8")

        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path("server.key")
        assert exc_info.value.error_code == PolicyErrorCode.SENSITIVE_FILE

        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path("cert.pem")
        assert exc_info.value.error_code == PolicyErrorCode.SENSITIVE_FILE

    def test_validate_path_nonexistent_must_exist(self, tmp_path: Path) -> None:
        ws = CodingWorkspace(tmp_path)
        with pytest.raises(FileNotFoundError):
            ws.validate_path("missing.txt", must_exist=True)

    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        secret_file = outside_dir / "secret.txt"
        secret_file.write_text("sensitive", encoding="utf-8")

        link_path = ws_dir / "link_to_outside"
        try:
            link_path.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation requires elevated privileges on this environment.")

        ws = CodingWorkspace(ws_dir)
        with pytest.raises(WorkspaceError) as exc_info:
            ws.validate_path("link_to_outside/secret.txt")
        assert exc_info.value.error_code == PolicyErrorCode.PATH_OUTSIDE_SANDBOX
