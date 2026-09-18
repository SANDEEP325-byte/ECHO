"""Coding Workspace Manager and Path Security (Phase 7A).

Enforces explicit, fail-closed authorized workspace root boundaries,
strict path containment, symlink/junction escape prevention, sensitive
file/directory shielding, and deterministic .gitignore-aware traversal.
"""

import os
import threading
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path

from services.desktop.policy import (
    DesktopSecurityPolicy,
    PolicyErrorCode,
    desktop_security_policy,
)
from services.logging.logger import logger  # type: ignore[attr-defined]


class WorkspaceError(PermissionError):
    """Raised when an operation violates coding workspace containment or security policies."""

    def __init__(
        self,
        reason: str,
        error_code: PolicyErrorCode | None = None,
        target_path: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_code = error_code
        self.target_path = target_path


class GitIgnoreMatcher:
    """Deterministic, standard-library .gitignore rule matcher.

    Supports:
    - Comments (#) and blank lines
    - Leading slashes (rooted patterns)
    - Trailing slashes (directory-only matches)
    - Negations (!)
    - Globbing (*, ?, [a-z], **)
    """

    # Always-excluded directories for safety and performance
    DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
        {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "build",
            "dist",
            ".egg-info",
            ".idea",
            ".vscode",
        }
    )

    def __init__(self, workspace_root: Path, extra_patterns: Sequence[str] | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.rules: list[tuple[bool, bool, str]] = []  # (is_negation, is_dir_only, pattern)
        self._load_root_gitignore()
        if extra_patterns:
            for p in extra_patterns:
                self._add_rule(p)

    def _add_rule(self, raw_line: str) -> None:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            return

        is_negation = False
        if line.startswith("!"):
            is_negation = True
            line = line[1:].strip()

        is_dir_only = line.endswith("/")
        if is_dir_only:
            line = line[:-1]

        # Strip leading slash for workspace-relative matching
        line = line.removeprefix("/")

        self.rules.append((is_negation, is_dir_only, line))

    def _load_root_gitignore(self) -> None:
        gitignore_path = self.workspace_root / ".gitignore"
        if gitignore_path.is_file():
            try:
                with gitignore_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        self._add_rule(line)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load root .gitignore at %s: %s", gitignore_path, exc)

    def is_ignored(self, path: Path, is_dir: bool = False) -> bool:
        """Evaluate whether a path relative to workspace_root matches ignore rules."""
        # 1. First check hardcoded excluded directory names
        for part in path.parts:
            if part in self.DEFAULT_EXCLUDED_DIRS:
                return True

        # Resolve relative path string in POSIX format for glob matching
        try:
            rel = path.resolve().relative_to(self.workspace_root)
            rel_str = rel.as_posix()
        except ValueError:
            return True  # Outside workspace is ignored/blocked

        matched = False
        name = path.name

        for is_negation, dir_only, pattern in self.rules:
            if dir_only and not is_dir:
                continue

            # Check matching against full relative path or filename
            if "/" in pattern:
                # Rooted or nested pattern
                if fnmatch(rel_str, pattern) or fnmatch(rel_str, f"**/{pattern}"):
                    matched = not is_negation
            else:
                # Basename pattern (e.g. *.pyc, temp)
                if fnmatch(name, pattern) or fnmatch(rel_str, f"**/{pattern}"):
                    matched = not is_negation

        return matched


class CodingWorkspace:
    """Manages explicit coding workspace root boundaries and path containment."""

    SENSITIVE_FILES: frozenset[str] = frozenset(
        {
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            "credentials",
            "credentials.json",
            "secrets.json",
            "master.key",
            "id_rsa",
            "id_ed25519",
            "id_ecdsa",
            "id_dsa",
        }
    )

    SENSITIVE_EXTENSIONS: frozenset[str] = frozenset(
        {
            ".pem",
            ".key",
            ".pfx",
            ".p12",
        }
    )

    def __init__(
        self,
        root_path: Path | str | None = None,
        desktop_policy: DesktopSecurityPolicy | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.desktop_policy = desktop_policy or desktop_security_policy
        self._root: Path | None = None
        self._matcher: GitIgnoreMatcher | None = None

        if root_path is not None:
            self.set_root(root_path)

    @property
    def root(self) -> Path:
        """Return the active authorized workspace root."""
        with self._lock:
            if self._root is None:
                # Default to Path.cwd() safely if within desktop policy
                self.set_root(Path.cwd())
            assert self._root is not None
            return self._root

    def set_root(self, path: Path | str) -> None:
        """Explicitly configure the authorized workspace root."""
        with self._lock:
            if not path:
                raise WorkspaceError(
                    reason="Workspace root path cannot be empty.",
                    error_code=PolicyErrorCode.INVALID_PATH,
                )

            resolved = Path(path).resolve()
            if not resolved.exists():
                raise WorkspaceError(
                    reason=f"Workspace root directory does not exist: '{resolved}'.",
                    error_code=PolicyErrorCode.INVALID_PATH,
                    target_path=str(resolved),
                )

            if not resolved.is_dir():
                raise WorkspaceError(
                    reason=f"Workspace root must be a directory, not a file: '{resolved}'.",
                    error_code=PolicyErrorCode.INVALID_PATH,
                    target_path=str(resolved),
                )

            # Prevent setting root to filesystem drive roots (e.g. C:\ or /)
            if resolved.parent == resolved:
                raise WorkspaceError(
                    reason="Filesystem root drives cannot be authorized as a coding workspace.",
                    error_code=PolicyErrorCode.PROTECTED_LOCATION,
                    target_path=str(resolved),
                )

            # Validate against protected desktop policy locations
            if self.desktop_policy._is_protected_location(resolved):
                raise WorkspaceError(
                    reason=f"Protected system directory '{resolved}' cannot be used as a workspace.",
                    error_code=PolicyErrorCode.PROTECTED_LOCATION,
                    target_path=str(resolved),
                )

            self._root = resolved
            self._matcher = GitIgnoreMatcher(self._root)
            logger.info("Coding workspace root set to: %s", self._root)

    def validate_path(
        self,
        raw_path: Path | str,
        must_exist: bool = False,
        allow_sensitive: bool = False,
    ) -> Path:
        """Validate and canonicalize a path against the authorized workspace root.

        Guarantees:
        1. Normalizes environment variables, tildes, and relative paths.
        2. Strictly rejects null bytes and UNC/network paths.
        3. Enforces strict containment inside workspace_root (including symlink resolution).
        4. Rejects protected system paths, sensitive directories (.git, .ssh, etc.),
           sensitive filenames (.env, id_rsa, secrets), and private key extensions.
        """
        if not raw_path:
            raise WorkspaceError(
                reason="Target path cannot be empty.",
                error_code=PolicyErrorCode.INVALID_PATH,
            )

        path_str = str(raw_path).strip()
        if "\x00" in path_str:
            raise WorkspaceError(
                reason="Path contains prohibited null byte characters.",
                error_code=PolicyErrorCode.INVALID_PATH,
                target_path=path_str,
            )

        # Reject UNC / network shares
        if path_str.startswith(("\\\\", "//")):
            raise WorkspaceError(
                reason="UNC network paths are strictly prohibited.",
                error_code=PolicyErrorCode.UNC_PATH_REJECTED,
                target_path=path_str,
            )

        with self._lock:
            current_root = self.root

            # Expand user and vars
            expanded = os.path.expandvars(os.path.expanduser(path_str))
            candidate = Path(expanded)
            if not candidate.is_absolute():
                candidate = current_root / candidate

            # Canonicalize
            resolved = candidate.resolve()

            # 1. Workspace containment check (fails closed against .. traversal & symlink escapes)
            try:
                # Will raise ValueError if resolved is not relative to current_root
                resolved.relative_to(current_root)
            except ValueError:
                raise WorkspaceError(
                    reason=f"Path '{resolved}' is outside the authorized workspace root '{current_root}'.",
                    error_code=PolicyErrorCode.PATH_OUTSIDE_SANDBOX,
                    target_path=str(resolved),
                ) from None

            # 2. Sensitive directory check (.git, .ssh, etc.)
            for part in resolved.parts:
                if part in self.desktop_policy.SENSITIVE_DIR_NAMES:
                    raise WorkspaceError(
                        reason=f"Access to sensitive directory component '{part}' is strictly prohibited.",
                        error_code=PolicyErrorCode.PROTECTED_LOCATION,
                        target_path=str(resolved),
                    )

            # 3. Sensitive file check (.env, credentials, id_rsa, private keys)
            if not allow_sensitive:
                if (
                    resolved.name.lower() in self.SENSITIVE_FILES
                    or resolved.name.lower() in self.desktop_policy.SENSITIVE_FILE_NAMES
                ):
                    raise WorkspaceError(
                        reason=f"Access to sensitive file '{resolved.name}' is strictly prohibited.",
                        error_code=PolicyErrorCode.SENSITIVE_FILE,
                        target_path=str(resolved),
                    )

                if (
                    resolved.suffix.lower() in self.SENSITIVE_EXTENSIONS
                    or resolved.suffix.lower() in self.desktop_policy.SENSITIVE_EXTENSIONS
                ):
                    raise WorkspaceError(
                        reason=f"Files with extension '{resolved.suffix}' are restricted as sensitive key material.",
                        error_code=PolicyErrorCode.SENSITIVE_FILE,
                        target_path=str(resolved),
                    )

            # 4. Existence check if requested
            if must_exist and not resolved.exists():
                raise FileNotFoundError(f"Target file does not exist: '{resolved}'.")

            return resolved

    def is_ignored(self, path: Path, is_dir: bool = False) -> bool:
        """Check if path is ignored by gitignore or hardcoded exclusion rules."""
        with self._lock:
            if self._matcher is None:
                self._matcher = GitIgnoreMatcher(self.root)
            return self._matcher.is_ignored(path, is_dir=is_dir)


# Singleton instance
workspace_manager = CodingWorkspace()
