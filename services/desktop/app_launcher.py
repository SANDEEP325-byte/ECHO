import os
from pathlib import Path
from typing import Any, Callable

from services.logging.logger import logger


class DesktopAppLauncher:
    """Safely launches verified, allowlisted Windows desktop applications.

    Accepts ONLY approved application identifiers. Arbitrary executable paths,
    scripts, and shell command strings are strictly prohibited and fail closed.
    """

    _ALIASES = {
        "calc": "calculator",
        "mspaint": "paint",
    }

    def __init__(self, os_launcher: Callable[[str | Path], None] | None = None) -> None:
        self.os_launcher = os_launcher
        self._allowlist = self._build_allowlist()

    def _build_allowlist(self) -> dict[str, dict[str, Any]]:
        system_root = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows")
        return {
            "notepad": {
                "description": "Windows Notepad text editor",
                "candidates": [
                    system_root / "System32" / "notepad.exe",
                    system_root / "notepad.exe",
                ],
            },
            "calculator": {
                "description": "Windows Calculator",
                "candidates": [
                    system_root / "System32" / "calc.exe",
                    system_root / "calc.exe",
                ],
            },
            "paint": {
                "description": "Windows Paint graphics editor",
                "candidates": [
                    system_root / "System32" / "mspaint.exe",
                ],
            },
        }

    def _launch(self, target: Path) -> None:
        """Execute the native launch hook or Windows os.startfile."""
        if self.os_launcher is not None:
            self.os_launcher(str(target))
        elif hasattr(os, "startfile"):
            os.startfile(str(target))
        else:
            raise NotImplementedError("OS launch requires Windows os.startfile or an injected launcher.")

    def normalize_app_name(self, raw_name: str) -> str:
        """Normalize and validate an application name against security constraints."""
        if not raw_name or not isinstance(raw_name, str):
            raise ValueError("Application name must be a non-empty string.")

        clean_name = raw_name.strip().lower()
        if not clean_name:
            raise ValueError("Application name cannot be empty.")

        # Reject path separators, special characters, and null bytes
        if any(char in clean_name for char in ("/\\:*?\"<>|\x00")):
            raise ValueError(
                f"Invalid application name: '{raw_name}'. File paths and special characters are prohibited."
            )

        # Reject file extensions (must be identifier only)
        if clean_name.endswith((".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh", ".py", ".msi", ".com")):
            raise ValueError(
                f"Executable and script extensions are prohibited in application name: '{raw_name}'."
            )

        return self._ALIASES.get(clean_name, clean_name)

    def is_allowlisted(self, raw_name: str) -> bool:
        """Check if an application identifier is present in the allowlist."""
        try:
            canonical = self.normalize_app_name(raw_name)
            return canonical in self._allowlist
        except ValueError:
            return False

    def resolve_application(self, raw_name: str) -> Path:
        """Resolve an allowlisted application name to a verified system executable path."""
        canonical = self.normalize_app_name(raw_name)

        if canonical not in self._allowlist:
            raise ValueError(
                f"Application '{raw_name}' is not in the approved application allowlist."
            )

        app_info = self._allowlist[canonical]
        for candidate in app_info["candidates"]:
            resolved = candidate.resolve(strict=False)
            if resolved.is_file():
                # Verify that resolved executable resides inside a trusted system directory
                system_root = Path(
                    os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
                ).resolve()
                try:
                    resolved.relative_to(system_root)
                except ValueError:
                    raise PermissionError(
                        f"Application target for '{raw_name}' resides outside trusted system directory."
                    )
                return resolved

        raise FileNotFoundError(
            f"Application '{raw_name}' is allowlisted, but its verified executable was not found on this system."
        )

    def launch_application(self, application_name: str) -> dict[str, Any]:
        """Launch an allowlisted application by identifier."""
        canonical = self.normalize_app_name(application_name)
        executable_path = self.resolve_application(canonical)

        logger.info("Launching allowlisted desktop application: {} ({})", canonical, executable_path)
        self._launch(executable_path)

        return {
            "operation": "open_application",
            "application": canonical,
            "path": str(executable_path),
            "status": "launched",
            "verified": True,
        }


desktop_app_launcher = DesktopAppLauncher()
