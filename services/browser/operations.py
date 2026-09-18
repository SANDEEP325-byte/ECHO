"""ECHO Browser Operations (Phase 5C, 5D, 5E, 5F).

Implements safe browser navigation, inspection, controlled interaction, and file transfers:
- browser_navigate: Safe HTTP/HTTPS navigation with pre/post URL validation,
  redirect safety, SSRF blocking, bounded timeouts, and structured outputs.
- browser_read_page: Safe page inspection extracting title, final URL, and
  bounded inner text without arbitrary JavaScript evaluation.
- browser_click: Bounded element targeting using Playwright locator semantics,
  element existence checks, post-click navigation validation, and confirmation hooks.
- browser_type: Bounded controlled text input with sensitive secret redaction,
  bounded length, and safe form submission.
- browser_download: Controlled file download via URL or element click into an
  authorized DesktopSecurityPolicy sandbox location with executable blocking.
- browser_upload: Controlled local file upload from an authorized sandbox location
  into an element with size bounding and sensitive file protection.

SECURITY RULES:
- No arbitrary evaluate() or evaluate_handle().
- No arbitrary JavaScript execution.
- Webpage content is treated strictly as UNTRUSTED DATA.
- Sensitive secret inputs are never returned in tool results or leaked in logs.
- All download destinations and upload sources are strictly sandbox-bound.
- Executable or script downloads are strictly prohibited.
"""

import re
from pathlib import Path
from typing import Any, ClassVar

from services.browser.errors import (
    BrowserError,
    BrowserSessionClosedError,
    BrowserTimeoutError,
)
from services.browser.policy import (
    BrowserPolicyErrorCode,
    BrowserSecurityPolicy,
    BrowserSecurityPolicyError,
    browser_security_policy,
)
from services.browser.service import BrowserService, browser_service
from services.browser.session import BrowserSession
from services.desktop.policy import (
    DesktopSecurityPolicy,
    OperationType,
    SecurityPolicyError,
    desktop_security_policy,
)
from services.logging.logger import logger  # type: ignore[attr-defined]


class BrowserOperations:
    """Orchestrates safe browser navigation, inspection, interaction, and file transfers."""

    MAX_SELECTOR_LENGTH = 500
    MAX_TEXT_LENGTH = 10000
    MAX_READ_CONTENT_LENGTH = 50000
    DEFAULT_READ_CONTENT_LENGTH = 10000
    MIN_TIMEOUT_MS = 1000
    MAX_TIMEOUT_MS = 60000

    MAX_DOWNLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
    MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

    BLOCKED_DOWNLOAD_EXTENSIONS: ClassVar[set[str]] = {
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
        ".dll",
        ".sys",
        ".drv",
        ".jar",
        ".app",
        ".dmg",
        ".pkg",
        ".sh",
        ".bash",
    }

    _CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
    _PROHIBITED_SELECTOR_PATTERNS = (
        "javascript:",
        "<script",
        "</script",
    )

    def __init__(
        self,
        service: BrowserService | None = None,
        security_policy: BrowserSecurityPolicy | None = None,
        desktop_policy: DesktopSecurityPolicy | None = None,
    ) -> None:
        self.service = service or browser_service
        self.security_policy = security_policy or browser_security_policy
        self.desktop_policy = desktop_policy or desktop_security_policy

    async def _ensure_session(self, session_id: str | None = None) -> BrowserSession:
        """Resolve active session by ID, or retrieve/create default active session."""
        if session_id is not None:
            session = await self.service.get_session(session_id)
            if session is None or not session.is_active():
                raise BrowserSessionClosedError(
                    f"Browser session '{session_id}' is closed, expired, or does not exist."
                )
            return session

        return await self.service.get_or_create_default_session()

    def _validate_selector(self, selector: str) -> str:
        """Validate and sanitize an element selector string."""
        if not selector or not isinstance(selector, str):
            raise BrowserError("Element selector cannot be empty or non-string.")

        clean = selector.strip()
        if not clean:
            raise BrowserError("Element selector cannot be whitespace-only.")

        if len(clean) > self.MAX_SELECTOR_LENGTH:
            raise BrowserError(
                f"Element selector exceeds maximum allowed length ({self.MAX_SELECTOR_LENGTH} characters)."
            )

        if self._CONTROL_CHAR_RE.search(clean):
            raise BrowserError("Element selector contains prohibited control characters.")

        clean_lower = clean.lower()
        for pattern in self._PROHIBITED_SELECTOR_PATTERNS:
            if pattern in clean_lower:
                raise BrowserError(f"Element selector contains prohibited pattern '{pattern}'.")

        return clean

    def _sanitize_download_path(
        self,
        destination_path: str | Path,
        suggested_filename: str | None = None,
    ) -> Path:
        """Validate and sanitize target download destination path against DesktopSecurityPolicy.

        Guarantees:
        - Path cannot be empty or blank.
        - Rejects null bytes, UNC paths (\\\\ or //), path traversal.
        - Normalizes and validates against desktop_security_policy for OperationType.CREATE.
        - If destination is an existing directory, combines with sanitized suggested_filename.
        - Rejects prohibited executable/script extensions.
        """
        if not destination_path:
            raise BrowserError("Download destination path cannot be empty.")

        path_str = str(destination_path).strip()
        if not path_str:
            raise BrowserError("Download destination path cannot be blank.")

        if "\x00" in path_str:
            raise BrowserError("Download destination path contains prohibited null byte.")

        if path_str.startswith((r"\\", "//")):
            raise BrowserError("Network and UNC destination paths are prohibited.")

        # Validate with DesktopSecurityPolicy
        try:
            resolved = self.desktop_policy.normalize_path(path_str)
        except SecurityPolicyError as exc:
            raise BrowserSecurityPolicyError(
                f"Download destination violates security policy: {exc.reason}",
                BrowserPolicyErrorCode.INVALID_URL,
            ) from exc

        # If destination is an existing directory or ends with path separator, combine with suggested_filename
        if resolved.is_dir() or path_str.endswith(("/", "\\")):
            base_name = suggested_filename if suggested_filename else "download"

            # Sanitize suggested filename: extract basename only, strip null bytes, control characters, traversal
            clean_name = Path(base_name).name.strip()
            clean_name = self._CONTROL_CHAR_RE.sub("", clean_name)
            clean_name = clean_name.replace("\x00", "")
            if not clean_name or clean_name in (".", ".."):
                clean_name = "download"

            target = resolved / clean_name
        else:
            target = resolved

        # Re-validate combined target path against policy
        check = self.desktop_policy.validate(target, OperationType.CREATE)
        if not check.allowed:
            raise BrowserSecurityPolicyError(
                f"Download destination path '{target}' is not permitted: {check.reason}",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        # Check extension against BLOCKED_DOWNLOAD_EXTENSIONS
        ext = target.suffix.lower()
        if ext in self.BLOCKED_DOWNLOAD_EXTENSIONS:
            raise BrowserSecurityPolicyError(
                f"Download destination file extension '{ext}' is prohibited by browser security policy.",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        # Also check suggested_filename extension if available
        if suggested_filename:
            sugg_ext = Path(suggested_filename).suffix.lower()
            if sugg_ext in self.BLOCKED_DOWNLOAD_EXTENSIONS:
                raise BrowserSecurityPolicyError(
                    f"Suggested download filename extension '{sugg_ext}' is prohibited by browser security policy.",
                    BrowserPolicyErrorCode.INVALID_URL,
                )

        return target

    def _validate_upload_path(self, file_path: str | Path) -> Path:
        """Validate and resolve upload source path against DesktopSecurityPolicy.

        Guarantees:
        - Source path cannot be empty or blank.
        - Rejects null bytes, UNC paths, traversal.
        - Validates against desktop_policy for OperationType.READ.
        - Must exist and be a regular file.
        - Must not be a sensitive credential/key file.
        - File size must not exceed MAX_UPLOAD_SIZE_BYTES.
        """
        if not file_path:
            raise BrowserError("Upload file path cannot be empty.")

        path_str = str(file_path).strip()
        if not path_str:
            raise BrowserError("Upload file path cannot be blank.")

        if "\x00" in path_str:
            raise BrowserError("Upload file path contains prohibited null byte.")

        if path_str.startswith((r"\\", "//")):
            raise BrowserError("Network and UNC file paths are prohibited.")

        # Check with DesktopSecurityPolicy
        check = self.desktop_policy.validate(path_str, OperationType.READ)
        if not check.allowed:
            raise BrowserSecurityPolicyError(
                f"Upload source path '{path_str}' is not permitted: {check.reason}",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        try:
            resolved = self.desktop_policy.normalize_path(path_str)
        except SecurityPolicyError as exc:
            raise BrowserSecurityPolicyError(
                f"Upload source path violates security policy: {exc.reason}",
                BrowserPolicyErrorCode.INVALID_URL,
            ) from exc

        if not resolved.exists():
            raise BrowserError(f"Upload source file does not exist: '{resolved.name}'.")

        if not resolved.is_file():
            raise BrowserError(f"Upload source path is not a regular file: '{resolved.name}'.")

        # Check sensitive file names and extensions (extra defense-in-depth)
        name_lower = resolved.name.lower()
        if name_lower in self.desktop_policy.SENSITIVE_FILE_NAMES:
            raise BrowserSecurityPolicyError(
                f"Access to sensitive file '{resolved.name}' is prohibited.",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        ext_lower = resolved.suffix.lower()
        if ext_lower in self.desktop_policy.SENSITIVE_EXTENSIONS:
            raise BrowserSecurityPolicyError(
                f"Access to files with extension '{ext_lower}' is prohibited.",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        size = resolved.stat().st_size
        if size > self.MAX_UPLOAD_SIZE_BYTES:
            raise BrowserError(
                f"Upload file size ({size} bytes) exceeds maximum limit ({self.MAX_UPLOAD_SIZE_BYTES} bytes)."
            )

        return resolved

    # =========================================================================
    # Phase 5C — Navigation & Inspection
    # =========================================================================

    async def navigate(
        self,
        url: str,
        session_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Navigate to an authorized URL with pre/post security checks and timeout bounding.

        Requirements:
        - Validate initial URL against BrowserSecurityPolicy.
        - Enforce HTTP/HTTPS only; reject dangerous schemes and private/metadata targets.
        - Execute navigation with bounded timeout.
        - Validate final destination URL post-redirects.
        - Return structured dictionary without leaking credentials or internals.
        """
        # 1. Pre-navigation security check
        check = self.security_policy.validate_url_or_raise(url)
        norm_url = check.normalized_url or url

        # 2. Resolve active session and page
        session = await self._ensure_session(session_id)
        page = session.primary_page

        # 3. Bound timeout
        nav_timeout = max(
            self.MIN_TIMEOUT_MS,
            min(timeout_ms or session.timeout_ms, self.MAX_TIMEOUT_MS),
        )

        logger.info(
            "Navigating session '%s' to '%s' (timeout=%dms)...",
            session.session_id,
            norm_url,
            nav_timeout,
        )

        # 4. Execute navigation
        response = None
        try:
            response = await page.goto(norm_url, timeout=nav_timeout)
        except Exception as exc:
            err_str = str(exc)
            if "Timeout" in type(exc).__name__ or "timeout" in err_str.lower():
                logger.error("Navigation timeout for '%s' after %dms", norm_url, nav_timeout)
                raise BrowserTimeoutError(
                    f"Navigation to '{url}' timed out after {nav_timeout}ms."
                ) from exc

            if "ERR_BLOCKED_BY_CLIENT" in err_str or "blockedbyclient" in err_str:
                logger.warning("Navigation request blocked by client security route: %s", url)
                raise BrowserSecurityPolicyError(
                    f"Navigation to '{url}' was blocked by the browser security policy.",
                    BrowserPolicyErrorCode.INVALID_URL,
                ) from exc

            logger.error("Navigation failed for '%s': %s", norm_url, exc)
            raise BrowserError(f"Navigation failed: {exc}") from exc

        # 5. Post-navigation security check on final URL
        final_url = getattr(page, "url", norm_url)
        final_check = self.security_policy.validate_url(final_url)
        if not final_check.allowed:
            logger.warning(
                "Final navigation destination '%s' violates policy: %s (code=%s)",
                final_url,
                final_check.reason,
                final_check.reason_code,
            )
            # Reset page away from untrusted location
            try:
                await page.goto("about:blank")
            except Exception as reset_exc:  # noqa: BLE001
                logger.debug("Failed to reset page to about:blank: %s", reset_exc)

            raise BrowserSecurityPolicyError(
                f"Navigation destination '{final_url}' violates browser security policy: {final_check.reason}",
                final_check.reason_code or BrowserPolicyErrorCode.INVALID_URL,
                normalized_url=final_check.normalized_url,
            )

        # 6. Extract page title safely
        title = ""
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""

        status_code = getattr(response, "status", 200) if response else None

        logger.info(
            "Successfully navigated to '%s' (final_url='%s', status=%s, title='%s')",
            norm_url,
            final_url,
            status_code,
            title,
        )

        return {
            "operation": "browser_navigate",
            "url": final_url,
            "initial_url": norm_url,
            "title": title or "",
            "status": status_code,
            "session_id": session.session_id,
            "success": True,
        }

    async def read_page(
        self,
        session_id: str | None = None,
        max_length: int = DEFAULT_READ_CONTENT_LENGTH,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Safely extract readable page text and metadata without arbitrary JavaScript.

        Guarantees:
        - No evaluate() or evaluate_handle().
        - Text is bounded to prevent memory abuse.
        - Content is treated as UNTRUSTED DATA.
        - Missing title or body handled gracefully.
        """
        session = await self._ensure_session(session_id)
        page = session.primary_page

        bounded_max_length = max(100, min(max_length, self.MAX_READ_CONTENT_LENGTH))
        read_timeout = max(500, min(timeout_ms or 5000, 10000))

        url = getattr(page, "url", "about:blank")
        title = ""
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""

        content = ""
        try:
            # Safe Playwright locator inner text extraction
            if hasattr(page, "locator"):
                body = page.locator("body")
                if hasattr(body, "count") and await body.count() > 0:
                    content = await body.inner_text(timeout=read_timeout)
                else:
                    root = page.locator(":root")
                    if hasattr(root, "count") and await root.count() > 0:
                        content = await root.inner_text(timeout=read_timeout)
            elif hasattr(page, "inner_text"):
                content = await page.inner_text("body", timeout=read_timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not extract inner text from page: %s", exc)
            content = ""

        truncated = len(content) > bounded_max_length
        bounded_content = content[:bounded_max_length]

        logger.info(
            "Read page '%s': extracted %d characters (truncated=%s)",
            url,
            len(bounded_content),
            truncated,
        )

        return {
            "operation": "browser_read_page",
            "url": url,
            "title": title or "",
            "content": bounded_content,
            "content_length": len(bounded_content),
            "truncated": truncated,
            "session_id": session.session_id,
            "success": True,
        }

    # =========================================================================
    # Phase 5D — Controlled Interaction
    # =========================================================================

    async def click(
        self,
        selector: str,
        session_id: str | None = None,
        is_submit: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Click an element identified by selector on the active webpage.

        Requirements:
        - Bounded selector validation and timeout.
        - Verified target existence before clicking.
        - Detect post-click navigation and validate destination URL safety.
        - Return structured result.
        """
        clean_selector = self._validate_selector(selector)
        session = await self._ensure_session(session_id)
        page = session.primary_page

        act_timeout = max(
            self.MIN_TIMEOUT_MS,
            min(timeout_ms or 10000, 30000),
        )

        # Verify element exists
        locator = page.locator(clean_selector) if hasattr(page, "locator") else None
        if locator is not None and hasattr(locator, "count"):
            count = await locator.count()
            if count == 0:
                raise BrowserError(
                    f"Target element with selector '{clean_selector}' not found on the page."
                )
            target = locator.first if hasattr(locator, "first") else locator
        else:
            target = locator

        initial_url = getattr(page, "url", "about:blank")

        logger.info(
            "Clicking selector '%s' in session '%s' (is_submit=%s)...",
            clean_selector,
            session.session_id,
            is_submit,
        )

        try:
            if hasattr(target, "click"):
                await target.click(timeout=act_timeout)
        except Exception as exc:
            err_str = str(exc)
            if "Timeout" in type(exc).__name__ or "timeout" in err_str.lower():
                raise BrowserTimeoutError(
                    f"Click on selector '{clean_selector}' timed out after {act_timeout}ms."
                ) from exc
            raise BrowserError(f"Click failed on selector '{clean_selector}': {exc}") from exc

        # Check for post-click navigation
        final_url = getattr(page, "url", initial_url)
        navigation_occurred = (
            final_url != initial_url and final_url != "about:blank" and initial_url != "about:blank"
        )

        if navigation_occurred:
            final_check = self.security_policy.validate_url(final_url)
            if not final_check.allowed:
                logger.warning(
                    "Post-click destination URL '%s' violates policy: %s",
                    final_url,
                    final_check.reason,
                )
                try:
                    await page.goto("about:blank")
                except Exception as reset_exc:  # noqa: BLE001
                    logger.debug("Failed to reset page to about:blank: %s", reset_exc)

                raise BrowserSecurityPolicyError(
                    f"Post-click navigation to '{final_url}' violates browser security policy: {final_check.reason}",
                    final_check.reason_code or BrowserPolicyErrorCode.INVALID_URL,
                    normalized_url=final_check.normalized_url,
                )

        logger.info(
            "Click completed for '%s' (navigation_occurred=%s, final_url='%s')",
            clean_selector,
            navigation_occurred,
            final_url,
        )

        return {
            "operation": "browser_click",
            "selector": clean_selector,
            "url": final_url,
            "navigation_occurred": navigation_occurred,
            "session_id": session.session_id,
            "success": True,
        }

    async def type_text(
        self,
        selector: str,
        text: str,
        session_id: str | None = None,
        is_sensitive: bool = False,
        submit: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Fill text into an element identified by selector on the active webpage.

        Requirements:
        - Bounded selector and text length (max 10000 chars).
        - Verify target exists before filling.
        - Redact sensitive inputs from logs and return structures.
        - If submit=True, press Enter and validate resulting destination URL.
        - Return structured result without leaking secret data.
        """
        clean_selector = self._validate_selector(selector)

        if not isinstance(text, str):
            raise BrowserError("Input text must be a string.")

        if len(text) > self.MAX_TEXT_LENGTH:
            raise BrowserError(
                f"Input text exceeds maximum allowed length ({self.MAX_TEXT_LENGTH} characters, got {len(text)})."
            )

        session = await self._ensure_session(session_id)
        page = session.primary_page

        act_timeout = max(
            self.MIN_TIMEOUT_MS,
            min(timeout_ms or 10000, 30000),
        )

        # Verify element exists
        locator = page.locator(clean_selector) if hasattr(page, "locator") else None
        if locator is not None and hasattr(locator, "count"):
            count = await locator.count()
            if count == 0:
                raise BrowserError(
                    f"Target element with selector '{clean_selector}' not found on the page."
                )
            target = locator.first if hasattr(locator, "first") else locator
        else:
            target = locator

        initial_url = getattr(page, "url", "about:blank")

        if is_sensitive:
            logger.info(
                "Typing sensitive secret (length=%d) into selector '%s' (submit=%s)...",
                len(text),
                clean_selector,
                submit,
            )
        else:
            logger.info(
                "Typing text (length=%d) into selector '%s' (submit=%s)...",
                len(text),
                clean_selector,
                submit,
            )

        try:
            if hasattr(target, "fill"):
                await target.fill(text, timeout=act_timeout)

            if submit and hasattr(target, "press"):
                await target.press("Enter", timeout=act_timeout)
        except Exception as exc:
            err_str = str(exc)
            if "Timeout" in type(exc).__name__ or "timeout" in err_str.lower():
                raise BrowserTimeoutError(
                    f"Type action on selector '{clean_selector}' timed out after {act_timeout}ms."
                ) from exc
            raise BrowserError(f"Type action failed on selector '{clean_selector}': {exc}") from exc

        # Check for post-submit navigation
        final_url = getattr(page, "url", initial_url)
        navigation_occurred = (
            submit
            and final_url != initial_url
            and final_url != "about:blank"
            and initial_url != "about:blank"
        )

        if navigation_occurred:
            final_check = self.security_policy.validate_url(final_url)
            if not final_check.allowed:
                logger.warning(
                    "Post-submit destination URL '%s' violates policy: %s",
                    final_url,
                    final_check.reason,
                )
                try:
                    await page.goto("about:blank")
                except Exception as reset_exc:  # noqa: BLE001
                    logger.debug("Failed to reset page to about:blank: %s", reset_exc)

                raise BrowserSecurityPolicyError(
                    f"Post-submit navigation to '{final_url}' violates browser security policy: {final_check.reason}",
                    final_check.reason_code or BrowserPolicyErrorCode.INVALID_URL,
                    normalized_url=final_check.normalized_url,
                )

        logger.info(
            "Typing completed for '%s' (submitted=%s, navigation_occurred=%s)",
            clean_selector,
            submit,
            navigation_occurred,
        )

        # NEVER return raw secret text in the structured result
        return {
            "operation": "browser_type",
            "selector": clean_selector,
            "text_length": len(text),
            "is_sensitive": is_sensitive,
            "submitted": submit,
            "url": final_url,
            "session_id": session.session_id,
            "success": True,
        }

    # =========================================================================
    # Phase 5E — Secure File Transfer
    # =========================================================================

    async def download(
        self,
        destination_path: str,
        url: str | None = None,
        selector: str | None = None,
        session_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Download a file via URL navigation or element click into an authorized sandbox location.

        Requirements:
        - Must specify either url or selector (not both, not neither).
        - If url: pre-navigation policy check.
        - If selector: validate selector syntax and verify target exists.
        - destination_path pre-validation against DesktopSecurityPolicy and blocked extensions.
        - Bounded timeout.
        - Captures download using page.expect_download().
        - Saves to target_file, checks size, purges if oversized.
        - Returns structured result without leaking internal secrets.
        """
        if (url is None and selector is None) or (url is not None and selector is not None):
            raise BrowserError(
                "Provide either 'url' or 'selector' to initiate a download, not both or neither."
            )

        session = await self._ensure_session(session_id)
        page = session.primary_page

        act_timeout = max(
            self.MIN_TIMEOUT_MS,
            min(timeout_ms or session.timeout_ms, self.MAX_TIMEOUT_MS),
        )

        # Pre-validate destination path
        target_file = self._sanitize_download_path(destination_path)

        if url is not None:
            # Pre-validate URL
            check = self.security_policy.validate_url_or_raise(url)
            norm_url = check.normalized_url or url

            logger.info(
                "Initiating download from URL '%s' into '%s' (session='%s')...",
                norm_url,
                target_file.name,
                session.session_id,
            )

            try:
                async with page.expect_download(timeout=act_timeout) as download_info:
                    await page.goto(norm_url, timeout=act_timeout)
                download = await download_info.value
            except Exception as exc:
                err_str = str(exc)
                if "Timeout" in type(exc).__name__ or "timeout" in err_str.lower():
                    raise BrowserTimeoutError(
                        f"Download from URL '{url}' timed out after {act_timeout}ms."
                    ) from exc
                raise BrowserError(f"Download failed from URL '{url}': {exc}") from exc

        else:
            assert selector is not None
            clean_selector = self._validate_selector(selector)

            locator = page.locator(clean_selector) if hasattr(page, "locator") else None
            if locator is not None and hasattr(locator, "count"):
                count = await locator.count()
                if count == 0:
                    raise BrowserError(
                        f"Target element with selector '{clean_selector}' not found on the page."
                    )
                target = locator.first if hasattr(locator, "first") else locator
            else:
                target = locator

            logger.info(
                "Initiating download via click on selector '%s' into '%s' (session='%s')...",
                clean_selector,
                target_file.name,
                session.session_id,
            )

            try:
                async with page.expect_download(timeout=act_timeout) as download_info:
                    if hasattr(target, "click"):
                        await target.click(timeout=act_timeout)
                download = await download_info.value
            except Exception as exc:
                err_str = str(exc)
                if "Timeout" in type(exc).__name__ or "timeout" in err_str.lower():
                    raise BrowserTimeoutError(
                        f"Download via selector '{clean_selector}' timed out after {act_timeout}ms."
                    ) from exc
                raise BrowserError(
                    f"Download failed on selector '{clean_selector}': {exc}"
                ) from exc

        # Validate suggested filename from browser/server against policy
        suggested_name = getattr(download, "suggested_filename", "")
        if suggested_name:
            target_file = self._sanitize_download_path(
                destination_path, suggested_filename=suggested_name
            )

        # Save the downloaded file
        try:
            await download.save_as(str(target_file))
        except Exception as exc:
            raise BrowserError(f"Failed to save downloaded file to disk: {exc}") from exc

        # Post-download file size check
        if not target_file.exists():
            raise BrowserError(f"Downloaded file '{target_file.name}' was not created on disk.")

        file_size = target_file.stat().st_size
        if file_size > self.MAX_DOWNLOAD_SIZE_BYTES:
            try:
                target_file.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove oversized download '{}': {}", target_file, exc)
            raise BrowserError(
                f"Downloaded file size ({file_size} bytes) exceeds maximum limit ({self.MAX_DOWNLOAD_SIZE_BYTES} bytes)."
            )

        download_url = getattr(download, "url", url or getattr(page, "url", ""))

        logger.info(
            "Download completed: saved '%s' (%d bytes) to '%s'",
            target_file.name,
            file_size,
            target_file,
        )

        return {
            "operation": "browser_download",
            "file_name": target_file.name,
            "destination_path": str(target_file),
            "file_size": file_size,
            "url": download_url,
            "session_id": session.session_id,
            "success": True,
        }

    async def upload(
        self,
        selector: str,
        file_path: str,
        session_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Upload a local file from an authorized sandbox location into an element.

        Requirements:
        - Validate selector syntax and verify target exists.
        - Validate source file path against DesktopSecurityPolicy.
        - Verify file exists, size <= MAX_UPLOAD_SIZE_BYTES, non-sensitive.
        - Set input files via locator.set_input_files().
        - Validate any post-upload page URL navigation.
        - Return structured result.
        """
        clean_selector = self._validate_selector(selector)
        resolved_file = self._validate_upload_path(file_path)

        session = await self._ensure_session(session_id)
        page = session.primary_page

        act_timeout = max(
            self.MIN_TIMEOUT_MS,
            min(timeout_ms or 10000, 30000),
        )

        locator = page.locator(clean_selector) if hasattr(page, "locator") else None
        if locator is not None and hasattr(locator, "count"):
            count = await locator.count()
            if count == 0:
                raise BrowserError(
                    f"Target element with selector '{clean_selector}' not found on the page."
                )
            target = locator.first if hasattr(locator, "first") else locator
        else:
            target = locator

        initial_url = getattr(page, "url", "about:blank")

        logger.info(
            "Uploading file '%s' (%d bytes) to selector '%s' (session='%s')...",
            resolved_file.name,
            resolved_file.stat().st_size,
            clean_selector,
            session.session_id,
        )

        try:
            if hasattr(target, "set_input_files"):
                await target.set_input_files(str(resolved_file), timeout=act_timeout)
        except Exception as exc:
            err_str = str(exc)
            if "Timeout" in type(exc).__name__ or "timeout" in err_str.lower():
                raise BrowserTimeoutError(
                    f"Upload to selector '{clean_selector}' timed out after {act_timeout}ms."
                ) from exc
            raise BrowserError(f"Upload failed on selector '{clean_selector}': {exc}") from exc

        # Check for post-upload automatic navigation
        final_url = getattr(page, "url", initial_url)
        navigation_occurred = (
            final_url != initial_url and final_url != "about:blank" and initial_url != "about:blank"
        )

        if navigation_occurred:
            final_check = self.security_policy.validate_url(final_url)
            if not final_check.allowed:
                logger.warning(
                    "Post-upload destination URL '%s' violates policy: %s",
                    final_url,
                    final_check.reason,
                )
                try:
                    await page.goto("about:blank")
                except Exception as reset_exc:  # noqa: BLE001
                    logger.debug("Failed to reset page to about:blank: %s", reset_exc)

                raise BrowserSecurityPolicyError(
                    f"Post-upload navigation to '{final_url}' violates browser security policy: {final_check.reason}",
                    final_check.reason_code or BrowserPolicyErrorCode.INVALID_URL,
                    normalized_url=final_check.normalized_url,
                )

        file_size = resolved_file.stat().st_size
        logger.info(
            "Upload completed for '%s' to '%s' (navigation_occurred=%s)",
            resolved_file.name,
            clean_selector,
            navigation_occurred,
        )

        return {
            "operation": "browser_upload",
            "selector": clean_selector,
            "file_name": resolved_file.name,
            "file_size": file_size,
            "url": final_url,
            "navigation_occurred": navigation_occurred,
            "session_id": session.session_id,
            "success": True,
        }


browser_operations = BrowserOperations()
