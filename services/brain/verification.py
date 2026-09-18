import os
import tempfile
from pathlib import Path
from typing import Any

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.verification import (
    VerificationDetail,
    VerificationResult,
    VerificationStatus,
)
from services.desktop.policy import (
    DesktopSecurityPolicy,
    OperationType,
    SecurityPolicyError,
    desktop_security_policy,
)
from services.logging.logger import logger  # type: ignore[attr-defined]


class VerificationEngine:
    """Verifies whether an ECHO execution post-condition can be verified."""

    def __init__(
        self,
        desktop_policy: DesktopSecurityPolicy | None = None,
        browser_policy: Any | None = None,
    ) -> None:
        self.policy = desktop_policy
        self.browser_policy = browser_policy

    def _validate_safe_path(
        self,
        raw_path: str | Path | None,
        operation: OperationType = OperationType.READ,
    ) -> tuple[bool, str, Path | None]:
        """Validate target path against the sandbox policy without raising.

        Guarantees:
        1. Explicit path canonicalization.
        2. Strict rejection of null bytes, UNC paths, and traversal escapes.
        3. Strict rejection of protected locations and sensitive files.
        4. Enforcement of sandbox root boundaries.
        """
        if raw_path is None:
            return False, "Target path is missing.", None

        active_policy = self.policy or desktop_security_policy

        try:
            resolved = active_policy.normalize_path(raw_path)
        except SecurityPolicyError as spe:
            return False, spe.reason, None
        except Exception as exc:  # noqa: BLE001
            return False, f"Invalid path syntax: {exc}", None

        # 1. Protected System Location check
        if active_policy._is_protected_location(resolved):
            return False, "Access to system or root drive locations is strictly prohibited.", None

        # 2. Sensitive File / Credentials check
        if active_policy._is_sensitive_file(resolved):
            return (
                False,
                "Access to credentials, secrets, or environment configuration is prohibited.",
                None,
            )

        # 3. Sandbox Containment Check
        for root in active_policy.authorized_roots:
            if active_policy._is_component_contained(resolved, root):
                return True, "Path authorized within sandbox.", resolved

        # If using global default policy, permit temporary test directory
        if self.policy is None:
            temp_dir = Path(tempfile.gettempdir()).resolve()
            if active_policy._is_component_contained(resolved, temp_dir):
                return True, "Path authorized within temporary test workspace.", resolved

        return False, "Target path is outside the authorized desktop sandbox.", None

    def _verify_operation_postcondition(self, meta: dict[str, Any]) -> VerificationDetail:
        """Inspect and verify the post-condition state for an individual operation."""
        op = meta.get("operation", "unknown")

        try:
            if op == "create_file":
                raw_path = meta.get("path")
                is_safe, reason, target = self._validate_safe_path(raw_path, OperationType.READ)
                if not is_safe or target is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error: {reason}",
                        expected="Target file resides within authorized sandbox",
                        observed=f"Path safety violation: {reason}",
                    )

                if not target.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: created file '{target.name}' does not exist.",
                        expected="File exists at target path",
                        observed="Target does not exist",
                    )

                if not target.is_file():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: created file '{target.name}' is not a regular file.",
                        expected="Target is a regular file",
                        observed="Target exists but is not a regular file",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Created file '{target.name}' verified successfully.",
                    expected="Target file exists as a regular file",
                    observed="Regular file exists at target path",
                )

            elif op == "create_folder":
                raw_path = meta.get("path")
                is_safe, reason, target = self._validate_safe_path(raw_path, OperationType.READ)
                if not is_safe or target is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error: {reason}",
                        expected="Target directory resides within authorized sandbox",
                        observed=f"Path safety violation: {reason}",
                    )

                if not target.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: created directory '{target.name}' does not exist.",
                        expected="Directory exists at target path",
                        observed="Target does not exist",
                    )

                if not target.is_dir():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: created directory '{target.name}' is not a directory.",
                        expected="Target is a directory",
                        observed="Target exists but is not a directory",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Created directory '{target.name}' verified successfully.",
                    expected="Target directory exists",
                    observed="Directory exists at target path",
                )

            elif op == "copy_file":
                raw_src = meta.get("source")
                raw_dst = meta.get("destination")
                safe_src, r_src, src = self._validate_safe_path(raw_src, OperationType.READ)
                safe_dst, r_dst, dst = self._validate_safe_path(raw_dst, OperationType.READ)

                if not safe_src or src is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error on source: {r_src}",
                        expected="Source resides within authorized sandbox",
                        observed=f"Path safety violation: {r_src}",
                    )
                if not safe_dst or dst is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error on destination: {r_dst}",
                        expected="Destination resides within authorized sandbox",
                        observed=f"Path safety violation: {r_dst}",
                    )

                if not dst.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: copied destination '{dst.name}' does not exist.",
                        expected="Destination file exists",
                        observed="Destination does not exist",
                    )

                if not dst.is_file():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: copied destination '{dst.name}' is not a regular file.",
                        expected="Destination is a regular file",
                        observed="Destination exists but is not a regular file",
                    )

                if not src.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: source file '{src.name}' no longer exists after copy.",
                        expected="Source file remains present after copy",
                        observed="Source file is missing",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Copied file to '{dst.name}' verified successfully.",
                    expected="Destination exists and source remains present",
                    observed="Destination regular file exists and source is present",
                )

            elif op in ("rename_file", "move_file"):
                raw_src = meta.get("source")
                raw_dst = meta.get("destination")
                safe_src, r_src, src = self._validate_safe_path(raw_src, OperationType.READ)
                safe_dst, r_dst, dst = self._validate_safe_path(raw_dst, OperationType.READ)

                if not safe_src or src is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error on source: {r_src}",
                        expected="Source resides within authorized sandbox",
                        observed=f"Path safety violation: {r_src}",
                    )
                if not safe_dst or dst is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error on destination: {r_dst}",
                        expected="Destination resides within authorized sandbox",
                        observed=f"Path safety violation: {r_dst}",
                    )

                if not dst.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: destination '{dst.name}' does not exist.",
                        expected="Destination path exists",
                        observed="Destination does not exist",
                    )

                if src.resolve() != dst.resolve() and src.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: source '{src.name}' still exists after move.",
                        expected=f"Source path no longer exists after {op}",
                        observed="Source path still exists",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Operation {op} verified successfully for destination '{dst.name}'.",
                    expected="Destination exists and source path no longer exists",
                    observed="Destination exists and source removed",
                )

            elif op == "delete_file":
                raw_path = meta.get("path")
                is_safe, reason, target = self._validate_safe_path(raw_path, OperationType.READ)
                if not is_safe or target is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error: {reason}",
                        expected="Target path resides within authorized sandbox",
                        observed=f"Path safety violation: {reason}",
                    )

                if target.exists():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: deleted target '{target.name}' still exists.",
                        expected="Target path no longer exists",
                        observed="Target path still exists",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Deleted target '{target.name}' verified successfully.",
                    expected="Target path no longer exists",
                    observed="Target does not exist",
                )

            elif op in ("read_file", "list_folder"):
                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.NOT_APPLICABLE,
                    message="Verification is not applicable for read-only filesystem operations.",
                    expected="Read-only operation has no filesystem mutation post-condition",
                    observed="Read operation completed without state mutation",
                )

            elif op == "open_file":
                raw_path = meta.get("path")
                is_safe, reason, target = self._validate_safe_path(raw_path, OperationType.READ)
                if not is_safe or target is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error: {reason}",
                        expected="Target file resides within authorized sandbox",
                        observed=f"Path safety violation: {reason}",
                    )

                if not target.is_file():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: target file '{target.name}' does not exist.",
                        expected="Target file exists",
                        observed="Target file does not exist or is not a regular file",
                    )

                if not meta.get("verified"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Verification failed: open_file operation was not verified.",
                        expected="OS launch dispatch verified",
                        observed="OS launch dispatch not verified",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=(
                        f"Target file '{target.name}' verified and OS launch dispatch confirmed. "
                        "Application window lifecycle is not verified."
                    ),
                    expected="Target file exists and OS launch dispatch successful",
                    observed="File exists and OS dispatch succeeded; GUI lifecycle unverified",
                )

            elif op == "open_folder":
                raw_path = meta.get("path")
                is_safe, reason, target = self._validate_safe_path(raw_path, OperationType.READ)
                if not is_safe or target is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Verification security error: {reason}",
                        expected="Target directory resides within authorized sandbox",
                        observed=f"Path safety violation: {reason}",
                    )

                if not target.is_dir():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: target directory '{target.name}' does not exist.",
                        expected="Target directory exists",
                        observed="Target directory does not exist or is not a directory",
                    )

                if not meta.get("verified"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Verification failed: open_folder operation was not verified.",
                        expected="OS launch dispatch verified",
                        observed="OS launch dispatch not verified",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=(
                        f"Target directory '{target.name}' verified and OS launch dispatch confirmed. "
                        "File explorer window lifecycle is not verified."
                    ),
                    expected="Target directory exists and OS launch dispatch successful",
                    observed="Directory exists and OS dispatch succeeded; explorer lifecycle unverified",
                )

            elif op == "open_application":
                raw_path = meta.get("path")
                app_name = meta.get("application", "unknown")
                if not raw_path:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message="Verification failed: missing application executable path in result.",
                        expected="Verified executable path in result metadata",
                        observed="Path missing",
                    )

                target = Path(raw_path)
                system_root = Path(
                    os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
                ).resolve()
                try:
                    target.resolve(strict=False).relative_to(system_root)
                except ValueError:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message="Verification failed: application target resides outside trusted system directory.",
                        expected="Executable resides in trusted system directory",
                        observed="Executable outside system directory",
                    )

                if not target.is_file():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: application executable '{target.name}' does not exist.",
                        expected="Application executable exists",
                        observed="Application executable does not exist",
                    )

                if not meta.get("verified") or meta.get("status") != "launched":
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Verification failed: open_application operation was not verified.",
                        expected="Application launch confirmed",
                        observed="Application launch unconfirmed",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.NOT_APPLICABLE,
                    message=(
                        f"Application '{app_name}' launch dispatch completed. "
                        "Runtime process lifecycle and window state verification are not applicable without unsafe inspection."
                    ),
                    expected="Launch dispatch accepted; window and process lifecycle unverified",
                    observed="Executable verified and launch dispatched; runtime process monitoring is not applicable",
                )

            elif op in ("execute_command", "run_command"):
                cmd_family = meta.get("command", "unknown")
                if meta.get("timed_out"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Verification failed: command execution timed out.",
                        expected="Command completes within timeout limit",
                        observed="Command timed out",
                    )

                if meta.get("status") == "failed" and meta.get("exit_code") is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message="Verification failed: process execution failed without exit code.",
                        expected="Process completes and returns an integer exit code",
                        observed="Process launch failed before returning exit code",
                    )

                if meta.get("exit_code") is not None and meta.get("exit_code") != 0:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Verification failed: command exited with non-zero exit code {meta.get('exit_code')}.",
                        expected="Command exits with return code 0",
                        observed=f"Command exited with return code {meta.get('exit_code')}",
                    )

                if not meta.get("verified"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Verification failed: command operation was not verified.",
                        expected="Command execution verified",
                        observed="Command unverified",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Command '{cmd_family}' post-condition verified (exit code 0).",
                    expected="Command completes with exit code 0 within timeout and output limits",
                    observed="Command executed successfully (exit code 0, bounded output)",
                )

            elif op == "browser_open":
                if not meta.get("success"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser session launch failed.",
                        expected="Successful browser session launch",
                        observed=f"Failure: {meta.get('error', 'Execution unsuccessful')}",
                    )
                session_id = meta.get("session_id")
                if not session_id:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser session launch missing session identifier.",
                        expected="Valid browser session ID",
                        observed="Missing session ID",
                    )
                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser session '{session_id}' launch verified.",
                    expected="Browser session launched",
                    observed=f"Session active (id={session_id})",
                )

            elif op == "browser_close":
                if not meta.get("success"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser session closure failed.",
                        expected="Successful browser session closure",
                        observed=f"Failure: {meta.get('error', 'Execution unsuccessful')}",
                    )
                session_id = meta.get("session_id", "active")
                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser session '{session_id}' closure verified.",
                    expected="Browser session closed",
                    observed="Session closed cleanly",
                )

            elif op == "browser_navigate":
                if not meta.get("success"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser navigation failed.",
                        expected="Successful navigation",
                        observed=f"Failure: {meta.get('error', 'Execution unsuccessful')}",
                    )

                url = meta.get("url")
                if not url or not isinstance(url, str):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser navigation produced no valid destination URL.",
                        expected="Valid destination URL",
                        observed="Missing destination URL",
                    )

                from services.browser.policy import browser_security_policy

                active_browser_policy = self.browser_policy or browser_security_policy
                policy_check = active_browser_policy.validate_url(url)
                if not policy_check.allowed:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Navigation destination violates browser security policy: {policy_check.reason}",
                        expected="Compliant destination URL",
                        observed=f"Policy violation: {policy_check.reason}",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser successfully navigated to '{url}'.",
                    expected=f"Navigation to authorized URL '{url}'",
                    observed=f"Navigated to '{url}' (status={meta.get('status')})",
                )

            elif op == "browser_read_page":
                if not meta.get("success"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Reading browser page failed.",
                        expected="Successful page read",
                        observed=f"Failure: {meta.get('error', 'Execution unsuccessful')}",
                    )

                content_len = meta.get("content_length", 0)
                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser page inspection verified ({content_len} characters extracted).",
                    expected="Safe readable text extraction",
                    observed=f"Extracted {content_len} characters (truncated={meta.get('truncated', False)})",
                )

            elif op == "browser_click":
                if not meta.get("success"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser click operation failed.",
                        expected="Successful element click",
                        observed=f"Failure: {meta.get('error', 'Execution unsuccessful')}",
                    )

                selector = meta.get("selector", "")
                if not selector:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser click metadata missing selector.",
                        expected="Target selector",
                        observed="Missing selector",
                    )

                if meta.get("navigation_occurred"):
                    nav_url = meta.get("url")
                    if nav_url and nav_url != "about:blank":
                        from services.browser.policy import browser_security_policy

                        active_browser_policy = self.browser_policy or browser_security_policy
                        policy_check = active_browser_policy.validate_url(nav_url)
                        if not policy_check.allowed:
                            return VerificationDetail(
                                operation=op,
                                status=VerificationStatus.VERIFICATION_ERROR,
                                message=f"Post-click destination violates browser security policy: {policy_check.reason}",
                                expected="Compliant destination URL",
                                observed=f"Policy violation: {policy_check.reason}",
                            )
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFIED,
                        message=f"Browser click on '{selector}' verified with navigation to '{nav_url}'.",
                        expected=f"Click on '{selector}'",
                        observed=f"Click succeeded, navigated to '{nav_url}'",
                    )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser click on '{selector}' verified.",
                    expected=f"Click on '{selector}'",
                    observed="Element clicked successfully without navigation",
                )

            elif op == "browser_type":
                if not meta.get("success"):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser text input operation failed.",
                        expected="Successful text input",
                        observed=f"Failure: {meta.get('error', 'Execution unsuccessful')}",
                    )

                selector = meta.get("selector", "")
                if not selector:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser type metadata missing selector.",
                        expected="Target selector",
                        observed="Missing selector",
                    )

                if meta.get("submitted") and meta.get("url"):
                    nav_url = meta.get("url")
                    if nav_url and nav_url != "about:blank":
                        from services.browser.policy import browser_security_policy

                        active_browser_policy = self.browser_policy or browser_security_policy
                        policy_check = active_browser_policy.validate_url(nav_url)
                        if not policy_check.allowed:
                            return VerificationDetail(
                                operation=op,
                                status=VerificationStatus.VERIFICATION_ERROR,
                                message=f"Post-submit destination violates browser security policy: {policy_check.reason}",
                                expected="Compliant destination URL",
                                observed=f"Policy violation: {policy_check.reason}",
                            )

                text_len = meta.get("text_length", 0)
                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser text input into '{selector}' verified ({text_len} characters).",
                    expected=f"Text entered into '{selector}'",
                    observed=f"Entered {text_len} characters (submitted={meta.get('submitted', False)})",
                )

            elif op == "browser_download":
                if not meta.get("success"):
                    err_msg = str(meta.get("error", "Execution unsuccessful"))
                    status = (
                        VerificationStatus.VERIFICATION_ERROR
                        if "security policy" in err_msg.lower() or "prohibited" in err_msg.lower()
                        else VerificationStatus.NOT_VERIFIED
                    )
                    return VerificationDetail(
                        operation=op,
                        status=status,
                        message=f"Browser download failed: {err_msg}",
                        expected="Successful file download",
                        observed=f"Failure: {err_msg}",
                    )

                dest_path_str = meta.get("destination_path")
                if not dest_path_str or not isinstance(dest_path_str, str):
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser download metadata missing destination path.",
                        expected="Valid destination path",
                        observed="Missing destination path",
                    )

                # Validate destination through DesktopSecurityPolicy
                safe_dest, reason_dest, resolved_dest = self._validate_safe_path(
                    dest_path_str, OperationType.READ
                )
                if not safe_dest or resolved_dest is None:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Downloaded file destination violates desktop security policy: {reason_dest}",
                        expected="Authorized sandbox destination path",
                        observed=f"Policy violation: {reason_dest}",
                    )

                # Check prohibited executable/script extensions
                from services.browser.operations import BrowserOperations

                dest_path = resolved_dest
                if dest_path.suffix.lower() in BrowserOperations.BLOCKED_DOWNLOAD_EXTENSIONS:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Downloaded file has prohibited executable extension '{dest_path.suffix.lower()}'.",
                        expected="Non-executable downloaded file",
                        observed=f"Prohibited extension: {dest_path.suffix.lower()}",
                    )

                # Verify file exists on disk and is a regular file
                if not dest_path.exists() or not dest_path.is_file():
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Downloaded file '{dest_path.name}' not found on disk at '{dest_path}'.",
                        expected="Downloaded file exists on disk",
                        observed="File not found on disk",
                    )

                # Verify file size
                actual_size = dest_path.stat().st_size
                if actual_size <= 0:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message=f"Downloaded file '{dest_path.name}' is empty (0 bytes).",
                        expected="Non-empty downloaded file",
                        observed="Empty file (0 bytes)",
                    )

                if actual_size > BrowserOperations.MAX_DOWNLOAD_SIZE_BYTES:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        message=f"Downloaded file size ({actual_size} bytes) exceeds maximum limit ({BrowserOperations.MAX_DOWNLOAD_SIZE_BYTES} bytes).",
                        expected=f"File size <= {BrowserOperations.MAX_DOWNLOAD_SIZE_BYTES} bytes",
                        observed=f"Oversized file ({actual_size} bytes)",
                    )

                # If URL present, validate against browser security policy
                download_url = meta.get("url")
                if download_url and download_url != "about:blank":
                    from services.browser.policy import browser_security_policy

                    active_browser_policy = self.browser_policy or browser_security_policy
                    url_check = active_browser_policy.validate_url(download_url)
                    if not url_check.allowed:
                        return VerificationDetail(
                            operation=op,
                            status=VerificationStatus.VERIFICATION_ERROR,
                            message=f"Download URL violates browser security policy: {url_check.reason}",
                            expected="Compliant download URL",
                            observed=f"Policy violation: {url_check.reason}",
                        )

                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser download of '{dest_path.name}' verified ({actual_size} bytes saved).",
                    expected=f"File '{dest_path.name}' downloaded successfully",
                    observed=f"File saved to '{dest_path}' ({actual_size} bytes)",
                )

            elif op == "browser_upload":
                if not meta.get("success"):
                    err_msg = str(meta.get("error", "Execution unsuccessful"))
                    status = (
                        VerificationStatus.VERIFICATION_ERROR
                        if "security policy" in err_msg.lower() or "prohibited" in err_msg.lower()
                        else VerificationStatus.NOT_VERIFIED
                    )
                    return VerificationDetail(
                        operation=op,
                        status=status,
                        message=f"Browser upload failed: {err_msg}",
                        expected="Successful file upload",
                        observed=f"Failure: {err_msg}",
                    )

                selector = meta.get("selector", "")
                if not selector:
                    return VerificationDetail(
                        operation=op,
                        status=VerificationStatus.NOT_VERIFIED,
                        message="Browser upload metadata missing selector.",
                        expected="Target input selector",
                        observed="Missing selector",
                    )

                # Check post-upload navigation if occurred
                if meta.get("navigation_occurred"):
                    nav_url = meta.get("url")
                    if nav_url and nav_url != "about:blank":
                        from services.browser.policy import browser_security_policy

                        active_browser_policy = self.browser_policy or browser_security_policy
                        url_check = active_browser_policy.validate_url(nav_url)
                        if not url_check.allowed:
                            return VerificationDetail(
                                operation=op,
                                status=VerificationStatus.VERIFICATION_ERROR,
                                message=f"Post-upload destination violates browser security policy: {url_check.reason}",
                                expected="Compliant destination URL",
                                observed=f"Policy violation: {url_check.reason}",
                            )

                file_name = meta.get("file_name", "file")
                file_size = meta.get("file_size", 0)
                return VerificationDetail(
                    operation=op,
                    status=VerificationStatus.VERIFIED,
                    message=f"Browser upload of '{file_name}' into '{selector}' verified ({file_size} bytes).",
                    expected=f"Upload '{file_name}' into '{selector}'",
                    observed=f"Upload completed ({file_size} bytes, navigation_occurred={meta.get('navigation_occurred', False)})",
                )

            else:
                return VerificationDetail(
                    operation=str(op),
                    status=VerificationStatus.NOT_APPLICABLE,
                    message=f"Verification is not applicable for operation '{op}'.",
                    expected="N/A",
                    observed="N/A",
                )

        except Exception as exc:  # noqa: BLE001
            return VerificationDetail(
                operation=str(op),
                status=VerificationStatus.VERIFICATION_ERROR,
                message=f"Verification failed during check: {exc}",
                expected="Check completes safely",
                observed=f"Verification check exception: {exc}",
            )

    def verify(
        self,
        request: Request,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        """Verify whether an ECHO execution post-condition can be verified."""
        logger.info(
            "Starting verification for request {}",
            request.request_id,
        )

        request.status = RequestStatus.VERIFYING

        if request.error is not None:
            request.status = RequestStatus.FAILED
            logger.error(
                "Verification failed for request {}: {}",
                request.request_id,
                request.error,
            )
            return VerificationResult(
                success=False,
                status=VerificationStatus.NOT_VERIFIED,
                error=request.error,
            )

        if not execution_result.success:
            request.status = RequestStatus.FAILED
            error = execution_result.error or "Verification failed: execution was unsuccessful."
            request.error = error
            logger.error(
                "Verification failed for request {}: {}",
                request.request_id,
                error,
            )
            return VerificationResult(
                success=False,
                status=VerificationStatus.NOT_VERIFIED,
                error=error,
            )

        if execution_result.result is None:
            request.status = RequestStatus.FAILED
            error = "Verification failed: execution produced no result."
            request.error = error
            logger.error(
                "Verification failed for request {}: execution produced no result",
                request.request_id,
            )
            return VerificationResult(
                success=False,
                status=VerificationStatus.NOT_VERIFIED,
                error=error,
            )

        items_to_verify = (
            execution_result.result
            if isinstance(execution_result.result, list)
            else [execution_result.result]
        )

        details: list[VerificationDetail] = []
        overall_status = VerificationStatus.VERIFIED

        for item in items_to_verify:
            if isinstance(item, dict) and "operation" in item:
                detail = self._verify_operation_postcondition(item)
                details.append(detail)

                if detail.status == VerificationStatus.VERIFICATION_ERROR:
                    request.status = RequestStatus.FAILED
                    request.error = detail.message
                    logger.error(
                        "Verification error for request {}: {}",
                        request.request_id,
                        detail.message,
                    )
                    return VerificationResult(
                        success=False,
                        status=VerificationStatus.VERIFICATION_ERROR,
                        error=detail.message,
                        result=execution_result.result,
                        details=details,
                    )

                if detail.status == VerificationStatus.NOT_VERIFIED:
                    request.status = RequestStatus.FAILED
                    request.error = detail.message
                    logger.error(
                        "Verification failed for request {}: {}",
                        request.request_id,
                        detail.message,
                    )
                    return VerificationResult(
                        success=False,
                        status=VerificationStatus.NOT_VERIFIED,
                        error=detail.message,
                        result=execution_result.result,
                        details=details,
                    )

        if details and all(d.status == VerificationStatus.NOT_APPLICABLE for d in details):
            overall_status = VerificationStatus.NOT_APPLICABLE

        logger.info(
            "Verification completed successfully for request {} (status={})",
            request.request_id,
            overall_status.value,
        )

        return VerificationResult(
            success=True,
            status=overall_status,
            result=execution_result.result,
            details=details,
        )


verification_engine = VerificationEngine()
