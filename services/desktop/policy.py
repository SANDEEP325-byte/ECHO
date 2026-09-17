from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Sequence

from services.logging.logger import logger


class OperationType(str, Enum):
    """Supported filesystem operations within ECHO Desktop security."""

    READ = "read"
    CREATE = "create"
    WRITE = "write"
    MOVE = "move"
    COPY = "copy"
    RENAME = "rename"
    DELETE = "delete"
    LIST = "list"
    OPEN = "open"


class PolicyErrorCode(str, Enum):
    """Structured policy violation error codes."""

    INVALID_PATH = "invalid_path"
    UNC_PATH_REJECTED = "unc_path_rejected"
    PROTECTED_LOCATION = "protected_location"
    SENSITIVE_FILE = "sensitive_file"
    PATH_OUTSIDE_SANDBOX = "path_outside_sandbox"
    SYMLINK_ESCAPE = "symlink_escape"
    ROOT_DELETION_FORBIDDEN = "root_deletion_forbidden"
    DIRECTORY_DELETE_REJECTED = "directory_delete_rejected"


@dataclass(frozen=True)
class PolicyCheckResult:
    """Represents the structured result of a desktop security policy check."""

    allowed: bool
    reason: str
    error_code: PolicyErrorCode | None = None
    operation: OperationType | None = None
    target_path: str | None = None


class SecurityPolicyError(PermissionError):
    """Raised when an operation violates the desktop security policy."""

    def __init__(
        self,
        reason: str,
        error_code: PolicyErrorCode | None = None,
        operation: OperationType | None = None,
        target_path: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_code = error_code
        self.operation = operation
        self.target_path = target_path


class DesktopSecurityPolicy:
    """Centralized security policy and path sandbox validator for desktop operations."""

    # Explicit sensitive file names and key identifiers
    SENSITIVE_FILE_NAMES = {
        "credentials",
        "credentials.json",
        "secrets.json",
        "master.key",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
    }

    # Sensitive path components (directories that must never be accessed)
    SENSITIVE_DIR_NAMES = {
        ".ssh",
        ".aws",
        ".git",
        ".gnupg",
        ".secrets",
    }

    # Sensitive private key extensions
    SENSITIVE_EXTENSIONS = {
        ".pem",
        ".key",
        ".pfx",
        ".p12",
    }

    # Blocked extensions when opening files (prevent code/script execution via association)
    BLOCKED_OPEN_EXTENSIONS = {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".ps1",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".msc",
        ".msi",
        ".scr",
        ".pif",
        ".reg",
        ".cpl",
        ".hta",
    }

    def __init__(
        self,
        authorized_roots: Sequence[Path | str] | None = None,
        include_default_roots: bool = True,
    ) -> None:
        """Initialize the security policy with authorized roots.

        Args:
            authorized_roots: Optional explicit list of paths permitted for access.
            include_default_roots: Whether to include standard user folders and cwd.
        """
        self._roots: list[Path] = []

        if authorized_roots is not None:
            for root in authorized_roots:
                try:
                    resolved = Path(root).resolve()
                    if resolved not in self._roots:
                        self._roots.append(resolved)
                except Exception as exc:
                    logger.warning("Could not resolve authorized root {}: {}", root, exc)

        if include_default_roots and authorized_roots is None:
            home = Path.home()
            default_candidates = [
                home / "Desktop",
                home / "Documents",
                home / "Downloads",
                Path.cwd(),
            ]
            for candidate in default_candidates:
                try:
                    resolved = candidate.resolve()
                    if resolved not in self._roots:
                        self._roots.append(resolved)
                except Exception as exc:
                    logger.warning("Failed to resolve default root {}: {}", candidate, exc)

        # Build set of protected system locations
        self._protected_locations: list[Path] = self._build_protected_locations()

    @property
    def authorized_roots(self) -> list[Path]:
        """Return the current active list of authorized root paths."""
        return list(self._roots)

    def _build_protected_locations(self) -> list[Path]:
        """Collect standard Windows and system locations that are forbidden."""
        locations: list[Path] = []

        system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
        try:
            locations.append(Path(system_root).resolve())
            locations.append((Path(system_root) / "System32").resolve())
        except Exception:
            pass

        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            val = os.environ.get(env_var)
            if val:
                try:
                    locations.append(Path(val).resolve())
                except Exception:
                    pass

        return locations

    def normalize_path(self, raw_path: str | Path) -> Path:
        """Normalize an incoming path string or Path object into a canonical Path.

        Expands environment variables, user tilde, and canonicalizes components.
        """
        if not raw_path:
            raise SecurityPolicyError(
                reason="Filesystem path cannot be empty.",
                error_code=PolicyErrorCode.INVALID_PATH,
            )

        path_str = str(raw_path).strip()
        if not path_str:
            raise SecurityPolicyError(
                reason="Filesystem path cannot be blank.",
                error_code=PolicyErrorCode.INVALID_PATH,
            )

        # Reject null bytes
        if "\x00" in path_str:
            raise SecurityPolicyError(
                reason="Invalid path containing null byte.",
                error_code=PolicyErrorCode.INVALID_PATH,
            )

        # Reject UNC / network paths
        if path_str.startswith(r"\\") or path_str.startswith("//"):
            raise SecurityPolicyError(
                reason="Network and UNC paths are not permitted.",
                error_code=PolicyErrorCode.UNC_PATH_REJECTED,
            )

        # Expand environment variables (e.g. %USERPROFILE%, $HOME) and user tilde
        expanded_str = os.path.expandvars(path_str)
        expanded_str = os.path.expanduser(expanded_str)

        # Re-check for UNC after expansion
        if expanded_str.startswith(r"\\") or expanded_str.startswith("//"):
            raise SecurityPolicyError(
                reason="Network and UNC paths are not permitted.",
                error_code=PolicyErrorCode.UNC_PATH_REJECTED,
            )

        # Construct and resolve path
        try:
            path_obj = Path(expanded_str)
            # Use strict=False so non-existent files (e.g. for creation) can be resolved
            return path_obj.resolve(strict=False)
        except Exception as exc:
            raise SecurityPolicyError(
                reason=f"Failed to normalize path: {exc}",
                error_code=PolicyErrorCode.INVALID_PATH,
            ) from exc

    def _is_component_contained(self, target: Path, root: Path) -> bool:
        """Check if target path is component-wise contained within root (case-insensitive)."""
        target_parts = [p.lower() for p in target.parts]
        root_parts = [r.lower() for r in root.parts]

        if len(target_parts) < len(root_parts):
            return False

        return target_parts[:len(root_parts)] == root_parts

    def _is_protected_location(self, path: Path) -> bool:
        """Check whether path lies within a protected system directory or is a drive root."""
        # Check drive root (e.g. C:\ or D:\)
        if len(path.parts) <= 1 or path.parent == path:
            return True

        # Check Windows / Program Files locations
        for protected in self._protected_locations:
            if self._is_component_contained(path, protected):
                return True

        return False

    def _is_sensitive_file(self, path: Path) -> bool:
        """Check whether path references a sensitive credentials/secrets file or folder."""
        # Check any folder component in the path
        lower_parts = {part.lower() for part in path.parts}
        for sensitive_dir in self.SENSITIVE_DIR_NAMES:
            if sensitive_dir in lower_parts:
                return True

        filename = path.name.lower()

        # Check .env variants (.env, .env.local, .env.prod, etc.)
        if filename == ".env" or filename.startswith(".env."):
            return True

        # Check explicit sensitive filenames
        if filename in self.SENSITIVE_FILE_NAMES:
            return True

        # Check sensitive file extensions
        if path.suffix.lower() in self.SENSITIVE_EXTENSIONS:
            return True

        return False

    def validate(
        self,
        raw_path: str | Path,
        operation: OperationType = OperationType.READ,
    ) -> PolicyCheckResult:
        """Validate a path against the desktop security policy without raising.

        Returns a PolicyCheckResult with allowed=True or False and reason.
        """
        try:
            resolved_path = self.normalize_path(raw_path)
        except SecurityPolicyError as spe:
            return PolicyCheckResult(
                allowed=False,
                reason=spe.reason,
                error_code=spe.error_code,
                operation=operation,
                target_path=str(raw_path),
            )
        except Exception as exc:
            return PolicyCheckResult(
                allowed=False,
                reason=f"Invalid path: {exc}",
                error_code=PolicyErrorCode.INVALID_PATH,
                operation=operation,
                target_path=str(raw_path),
            )

        # 1. Protected System Location check
        if self._is_protected_location(resolved_path):
            return PolicyCheckResult(
                allowed=False,
                reason="Access to system or root drive locations is strictly prohibited.",
                error_code=PolicyErrorCode.PROTECTED_LOCATION,
                operation=operation,
                target_path=str(resolved_path),
            )

        # 2. Sensitive File / Credentials check
        if self._is_sensitive_file(resolved_path):
            return PolicyCheckResult(
                allowed=False,
                reason="Access to credentials, secrets, or environment configuration is prohibited.",
                error_code=PolicyErrorCode.SENSITIVE_FILE,
                operation=operation,
                target_path=str(resolved_path),
            )

        # 3. Sandbox Containment Check (Component-Aware)
        contained_in_root = False
        matched_root: Path | None = None
        for root in self._roots:
            if self._is_component_contained(resolved_path, root):
                contained_in_root = True
                matched_root = root
                break

        if not contained_in_root:
            return PolicyCheckResult(
                allowed=False,
                reason="Target path is outside the authorized desktop sandbox.",
                error_code=PolicyErrorCode.PATH_OUTSIDE_SANDBOX,
                operation=operation,
                target_path=str(resolved_path),
            )

        # 4. Operation-Specific Checks
        if operation == OperationType.OPEN:
            if resolved_path.suffix.lower() in self.BLOCKED_OPEN_EXTENSIONS:
                return PolicyCheckResult(
                    allowed=False,
                    reason="Opening executable, batch, or script files is strictly prohibited.",
                    error_code=PolicyErrorCode.SENSITIVE_FILE,
                    operation=operation,
                    target_path=str(resolved_path),
                )

        if operation in (OperationType.DELETE, OperationType.MOVE, OperationType.RENAME):
            # Cannot delete, move, or rename the authorized root itself
            if matched_root is not None:
                if [p.lower() for p in resolved_path.parts] == [r.lower() for r in matched_root.parts]:
                    return PolicyCheckResult(
                        allowed=False,
                        reason=f"Operating ({operation.value}) on an authorized sandbox root folder is forbidden.",
                        error_code=PolicyErrorCode.ROOT_DELETION_FORBIDDEN,
                        operation=operation,
                        target_path=str(resolved_path),
                    )

        return PolicyCheckResult(
            allowed=True,
            reason="Path authorized within sandbox.",
            operation=operation,
            target_path=str(resolved_path),
        )

    def validate_or_raise(
        self,
        raw_path: str | Path,
        operation: OperationType = OperationType.READ,
    ) -> Path:
        """Validate a path against the desktop security policy.

        Returns the resolved Path if allowed; raises SecurityPolicyError if rejected.
        """
        result = self.validate(raw_path, operation=operation)
        if not result.allowed:
            raise SecurityPolicyError(
                reason=result.reason,
                error_code=result.error_code,
                operation=operation,
                target_path=result.target_path or str(raw_path),
            )

        return Path(result.target_path)  # type: ignore[arg-type]


# Global default instance using standard desktop roots
desktop_security_policy = DesktopSecurityPolicy()
