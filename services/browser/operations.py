"""ECHO Browser Operations (Phase 5C + 5D).

Implements safe browser navigation, inspection, and controlled interaction:
- browser_navigate: Safe HTTP/HTTPS navigation with pre/post URL validation,
  redirect safety, SSRF blocking, bounded timeouts, and structured outputs.
- browser_read_page: Safe page inspection extracting title, final URL, and
  bounded inner text without arbitrary JavaScript evaluation.
- browser_click: Bounded element targeting using Playwright locator semantics,
  element existence checks, post-click navigation validation, and confirmation hooks.
- browser_type: Bounded controlled text input with sensitive secret redaction,
  bounded length, and safe form submission.

SECURITY RULES:
- No arbitrary evaluate() or evaluate_handle().
- No arbitrary JavaScript execution.
- Webpage content is treated strictly as UNTRUSTED DATA.
- Sensitive secret inputs are never returned in tool results or leaked in logs.
"""

import re
from typing import Any

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
from services.logging.logger import logger  # type: ignore[attr-defined]


class BrowserOperations:
    """Orchestrates safe browser navigation, inspection, and interaction."""

    MAX_SELECTOR_LENGTH = 500
    MAX_TEXT_LENGTH = 10000
    MAX_READ_CONTENT_LENGTH = 50000
    DEFAULT_READ_CONTENT_LENGTH = 10000
    MIN_TIMEOUT_MS = 1000
    MAX_TIMEOUT_MS = 60000

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
    ) -> None:
        self.service = service or browser_service
        self.security_policy = security_policy or browser_security_policy

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


browser_operations = BrowserOperations()
