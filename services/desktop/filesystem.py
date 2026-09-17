from pathlib import Path
import shutil
from typing import Any

from services.desktop.policy import (
    DesktopSecurityPolicy,
    OperationType,
    desktop_security_policy,
)
from services.logging.logger import logger


class FilesystemService:
    """Safe desktop filesystem service enforcing centralized security policy.

    All operations use standard Python pathlib/shutil and strictly avoid shell commands,
    system subprocesses, or unvalidated user paths.
    """

    def __init__(
        self,
        policy: DesktopSecurityPolicy | None = None,
        os_launcher: Any = None,
    ) -> None:
        self.policy = policy or desktop_security_policy
        self.os_launcher = os_launcher

    def _launch(self, target: Path) -> None:
        """Launch target using the configured OS launcher or Windows os.startfile."""
        if self.os_launcher is not None:
            self.os_launcher(str(target))
        elif hasattr(os, "startfile"):
            os.startfile(str(target))
        else:
            raise NotImplementedError("OS launch requires Windows os.startfile or an injected launcher.")

    def read_file(
        self,
        path: str | Path,
        max_bytes: int = 65536,
        encoding: str = "utf-8",
    ) -> str:
        """Read content from a text file within the authorized sandbox.

        Args:
            path: Target file path.
            max_bytes: Maximum number of bytes to read (default 64KB).
            encoding: Text encoding (default utf-8).

        Returns:
            String content of the file.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.READ)

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not resolved.is_file():
            raise IsADirectoryError(f"Target is a directory, not a file: {path}")

        logger.info("Reading file within sandbox: {}", resolved)

        with resolved.open("r", encoding=encoding, errors="replace") as f:
            return f.read(max_bytes)

    def list_folder(
        self,
        path: str | Path,
        include_hidden: bool = False,
    ) -> list[dict[str, Any]]:
        """List files and folders within an authorized directory.

        Args:
            path: Target directory path.
            include_hidden: Whether to include hidden files (starting with .).

        Returns:
            List of metadata dictionaries for entries in the folder.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.LIST)

        if not resolved.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        if not resolved.is_dir():
            raise NotADirectoryError(f"Target is not a directory: {path}")

        logger.info("Listing folder within sandbox: {}", resolved)

        entries = []
        for item in sorted(resolved.iterdir()):
            if not include_hidden and item.name.startswith("."):
                continue

            try:
                is_directory = item.is_dir()
                size = item.stat().st_size if not is_directory else 0
                entries.append(
                    {
                        "name": item.name,
                        "is_dir": is_directory,
                        "size": size,
                        "path": str(item),
                    }
                )
            except Exception:
                continue

        return entries

    def create_file(
        self,
        path: str | Path,
        content: str = "",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create a new file with text content.

        Args:
            path: Target file path.
            content: Text content to write.
            overwrite: If True, permits overwriting existing file; if False, fails safely.

        Returns:
            Operation metadata dictionary.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.CREATE)

        if resolved.exists():
            if not overwrite:
                raise FileExistsError(
                    f"File already exists and overwrite=False: {resolved.name}"
                )
            # Re-validate with WRITE operation when overwriting
            resolved = self.policy.validate_or_raise(path, OperationType.WRITE)

        # Ensure parent folder exists and is within sandbox
        parent = resolved.parent
        self.policy.validate_or_raise(parent, OperationType.CREATE)
        parent.mkdir(parents=True, exist_ok=True)

        logger.info("Writing file within sandbox: {} (size={})", resolved, len(content))
        resolved.write_text(content, encoding="utf-8")

        return {
            "operation": "create_file",
            "path": str(resolved),
            "size": len(content),
            "status": "overwritten" if overwrite and resolved.exists() else "created",
            "verified": True,
        }

    def create_folder(
        self,
        path: str | Path,
        exist_ok: bool = False,
    ) -> dict[str, Any]:
        """Create a new folder within the authorized sandbox.

        Args:
            path: Target directory path.
            exist_ok: If False, raises if folder already exists.

        Returns:
            Operation metadata dictionary.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.CREATE)

        if resolved.exists() and not exist_ok:
            raise FileExistsError(f"Folder already exists: {resolved.name}")

        logger.info("Creating folder within sandbox: {}", resolved)
        resolved.mkdir(parents=True, exist_ok=exist_ok)

        return {
            "operation": "create_folder",
            "path": str(resolved),
            "status": "created",
            "verified": True,
        }

    def copy_file(
        self,
        source: str | Path,
        destination: str | Path,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Copy a file from source to destination, validating both endpoints.

        Args:
            source: Source file path.
            destination: Destination file path.
            overwrite: If False, fails if destination exists.

        Returns:
            Operation metadata dictionary.
        """
        src_resolved = self.policy.validate_or_raise(source, OperationType.READ)
        dst_resolved = self.policy.validate_or_raise(destination, OperationType.CREATE)

        if not src_resolved.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        if not src_resolved.is_file():
            raise ValueError(f"Source must be a regular file: {source}")

        if dst_resolved.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Destination already exists and overwrite=False: {dst_resolved.name}"
                )
            self.policy.validate_or_raise(destination, OperationType.WRITE)

        # Ensure destination parent directory exists
        dst_resolved.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Copying file: {} -> {}", src_resolved, dst_resolved)
        shutil.copy2(src_resolved, dst_resolved)

        return {
            "operation": "copy_file",
            "source": str(src_resolved),
            "destination": str(dst_resolved),
            "status": "copied",
            "verified": True,
        }

    def rename_file(
        self,
        source: str | Path,
        destination: str | Path,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Rename a file or folder within authorized roots.

        Args:
            source: Source path.
            destination: Destination path.
            overwrite: If False, fails if destination exists.

        Returns:
            Operation metadata dictionary.
        """
        src_resolved = self.policy.validate_or_raise(source, OperationType.RENAME)
        dst_resolved = self.policy.validate_or_raise(destination, OperationType.CREATE)

        if not src_resolved.exists():
            raise FileNotFoundError(f"Source path not found: {source}")

        if dst_resolved.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Destination already exists and overwrite=False: {dst_resolved.name}"
                )
            self.policy.validate_or_raise(destination, OperationType.WRITE)

        dst_resolved.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Renaming path: {} -> {}", src_resolved, dst_resolved)
        src_resolved.rename(dst_resolved)

        return {
            "operation": "rename_file",
            "source": str(src_resolved),
            "destination": str(dst_resolved),
            "status": "renamed",
            "verified": True,
        }

    def move_file(
        self,
        source: str | Path,
        destination: str | Path,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Move a file or folder from source to destination.

        Args:
            source: Source path.
            destination: Destination path.
            overwrite: If False, fails if destination exists.

        Returns:
            Operation metadata dictionary.
        """
        src_resolved = self.policy.validate_or_raise(source, OperationType.MOVE)
        dst_resolved = self.policy.validate_or_raise(destination, OperationType.CREATE)

        if not src_resolved.exists():
            raise FileNotFoundError(f"Source path not found: {source}")

        if dst_resolved.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Destination already exists and overwrite=False: {dst_resolved.name}"
                )
            self.policy.validate_or_raise(destination, OperationType.WRITE)

        dst_resolved.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Moving path: {} -> {}", src_resolved, dst_resolved)
        shutil.move(str(src_resolved), str(dst_resolved))

        return {
            "operation": "move_file",
            "source": str(src_resolved),
            "destination": str(dst_resolved),
            "status": "moved",
            "verified": True,
        }

    def delete_file(
        self,
        path: str | Path,
        permanent: bool = False,
    ) -> dict[str, Any]:
        """Delete a file or empty folder within the authorized sandbox.

        Recursive directory deletion is strictly prohibited.

        Args:
            path: Target path to delete.
            permanent: Reserved for future Recycle Bin integration.

        Returns:
            Operation metadata dictionary.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.DELETE)

        if not resolved.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        if resolved.is_dir():
            # Strictly disallow recursive directory deletion
            if any(resolved.iterdir()):
                raise ValueError(
                    "Cannot delete non-empty directory. Recursive directory deletion is prohibited."
                )
            logger.info("Deleting empty directory within sandbox: {}", resolved)
            resolved.rmdir()
        else:
            logger.info("Deleting file within sandbox: {}", resolved)
            resolved.unlink()

        return {
            "operation": "delete_file",
            "path": str(resolved),
            "status": "deleted",
            "verified": True,
        }

    def open_file(self, path: str | Path) -> dict[str, Any]:
        """Open an authorized file using its default associated application.

        Executable and script files are strictly blocked.

        Args:
            path: Target file path.

        Returns:
            Operation metadata dictionary.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.OPEN)

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not resolved.is_file():
            raise IsADirectoryError(f"Target is a directory, not a file: {path}")

        logger.info("Opening file via associated application: {}", resolved)
        self._launch(resolved)

        return {
            "operation": "open_file",
            "path": str(resolved),
            "status": "opened",
            "verified": True,
        }

    def open_folder(self, path: str | Path) -> dict[str, Any]:
        """Open an authorized folder in Windows Explorer.

        Args:
            path: Target folder path.

        Returns:
            Operation metadata dictionary.
        """
        resolved = self.policy.validate_or_raise(path, OperationType.OPEN)

        if not resolved.exists():
            raise FileNotFoundError(f"Folder not found: {path}")

        if not resolved.is_dir():
            raise NotADirectoryError(f"Target is a file, not a directory: {path}")

        logger.info("Opening folder in file explorer: {}", resolved)
        self._launch(resolved)

        return {
            "operation": "open_folder",
            "path": str(resolved),
            "status": "opened",
            "verified": True,
        }


filesystem_service = FilesystemService()
