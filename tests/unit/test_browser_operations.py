"""Unit tests for ECHO Browser Operations (Phase 5C + Phase 5D).

Deterministic, 100% offline unit tests covering:
- Phase 5C: Safe navigation, scheme rejection, private IP rejection, redirect safety,
  route interception/SSRF, timeouts, title & text extraction, oversized content.
- Phase 5D: Safe click, element existence, post-click navigation, safe typing,
  secret redaction, submit navigation, input bounding.
"""

from typing import Any

import pytest

from services.browser.errors import (
    BrowserError,
    BrowserSessionClosedError,
    BrowserTimeoutError,
)
from services.browser.operations import BrowserOperations
from services.browser.policy import (
    BrowserPolicyErrorCode,
    BrowserSecurityPolicy,
    BrowserSecurityPolicyError,
)
from services.browser.service import BrowserService
from services.browser.session import BrowserSession

# ==============================================================================
# Mock Playwright Hierarchy for Offline Deterministic Testing
# ==============================================================================


class MockLocator:
    """Mock Playwright Locator with count, click, fill, press, and inner_text."""

    def __init__(
        self,
        selector: str,
        page: "MockPage",
        text_content: str = "",
        element_count: int = 1,
    ) -> None:
        self.selector = selector
        self.page = page
        self.text_content = text_content
        self.element_count = element_count
        self.clicked = False
        self.filled_text: str | None = None
        self.pressed_keys: list[str] = []
        self.click_timeout_error = False
        self.nav_on_click: str | None = None
        self.nav_on_submit: str | None = None

    @property
    def first(self) -> "MockLocator":
        return self

    async def count(self) -> int:
        return self.element_count

    async def click(self, timeout: int = 30000) -> None:
        if self.click_timeout_error:
            raise TimeoutError(f"Click timed out after {timeout}ms")
        self.clicked = True
        if self.nav_on_click:
            self.page.url = self.nav_on_click

    async def fill(self, text: str, timeout: int = 30000) -> None:
        self.filled_text = text

    async def press(self, key: str, timeout: int = 30000) -> None:
        self.pressed_keys.append(key)
        if key == "Enter" and self.nav_on_submit:
            self.page.url = self.nav_on_submit

    async def inner_text(self, timeout: int = 5000) -> str:
        return self.text_content


class MockResponse:
    """Mock Playwright HTTP Response."""

    def __init__(self, status: int = 200) -> None:
        self.status = status


class MockPage:
    """Mock Playwright Page."""

    def __init__(
        self,
        initial_url: str = "about:blank",
        initial_title: str = "Example Domain",
        body_text: str = "Example text content",
    ) -> None:
        self.url = initial_url
        self._title = initial_title
        self.body_text = body_text
        self.closed = False
        self.goto_calls: list[str] = []
        self.fail_goto_timeout = False
        self.fail_goto_blocked = False
        self.fail_goto_generic = False
        self.redirect_target: str | None = None
        self.element_counts: dict[str, int] = {}
        self.click_nav_map: dict[str, str] = {}
        self.submit_nav_map: dict[str, str] = {}

    async def goto(self, url: str, timeout: int = 30000, wait_until: str = "load") -> MockResponse:
        self.goto_calls.append(url)
        if self.fail_goto_timeout:
            raise TimeoutError(f"Navigation timed out after {timeout}ms")
        if self.fail_goto_blocked:
            raise RuntimeError("net::ERR_BLOCKED_BY_CLIENT at " + url)
        if self.fail_goto_generic:
            raise RuntimeError("Generic network failure")

        if self.redirect_target is not None:
            self.url = self.redirect_target
        else:
            self.url = url
        return MockResponse(status=200)

    async def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> MockLocator:
        count = self.element_counts.get(selector, 1)
        text = self.body_text if selector in ("body", ":root") else "Element text"
        loc = MockLocator(selector=selector, page=self, text_content=text, element_count=count)
        if selector in self.click_nav_map:
            loc.nav_on_click = self.click_nav_map[selector]
        if selector in self.submit_nav_map:
            loc.nav_on_submit = self.submit_nav_map[selector]
        return loc

    async def close(self) -> None:
        self.closed = True


class MockRoute:
    """Mock Playwright Route for testing request interception."""

    def __init__(self) -> None:
        self.aborted = False
        self.abort_reason: str | None = None
        self.continued = False

    async def abort(self, errorCode: str = "failed") -> None:
        self.aborted = True
        self.abort_reason = errorCode

    async def continue_(self) -> None:
        self.continued = True


class MockRequest:
    """Mock Playwright Request."""

    def __init__(self, url: str) -> None:
        self.url = url


class MockBrowserContext:
    """Mock Playwright BrowserContext supporting route interception."""

    def __init__(self) -> None:
        self.closed = False
        self.routes: list[tuple[str, Any]] = []
        self.default_timeout = 30000

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    async def route(self, pattern: str, handler: Any) -> None:
        self.routes.append((pattern, handler))

    async def close(self) -> None:
        self.closed = True


# ==============================================================================
# Test Fixtures & Helpers
# ==============================================================================


def make_mock_policy() -> BrowserSecurityPolicy:
    """Create a test BrowserSecurityPolicy with static DNS resolution."""
    dns_map = {
        "example.com": ["93.184.216.34"],
        "safe.org": ["198.51.100.1"],
        "evil.com": ["192.168.1.100"],  # Resolves to private RFC 1918
        "rebinding.com": ["127.0.0.1"],  # Resolves to loopback
    }

    def mock_dns(host: str) -> list[str]:
        return dns_map.get(host, ["93.184.216.34"])

    return BrowserSecurityPolicy(
        enforce_dns_resolution=True,
        dns_resolver=mock_dns,
    )


def make_test_service(
    page: MockPage, policy: BrowserSecurityPolicy
) -> tuple[BrowserService, BrowserSession]:
    """Assemble a BrowserService with a pre-created MockPage in an active session."""
    context = MockBrowserContext()
    service = BrowserService(security_policy=policy)
    service._state = service.state.RUNNING

    session = BrowserSession(
        session_id="test_session_123",
        context=context,
        primary_page=page,
        timeout_ms=30000,
        on_close=service._on_session_closed,
    )
    service._sessions[session.session_id] = session
    return service, session


# ==============================================================================
# Phase 5C: Navigation & Inspection Unit Tests
# ==============================================================================


@pytest.mark.anyio
async def test_navigate_allowed_https_success() -> None:
    """Phase 5C: Allowed HTTPS navigation returns structured result."""
    policy = make_mock_policy()
    page = MockPage(initial_title="Example Page", body_text="Hello World")
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    res = await ops.navigate("https://example.com/docs", session_id=session.session_id)

    assert res["success"] is True
    assert res["operation"] == "browser_navigate"
    assert res["url"] == "https://example.com/docs"
    assert res["initial_url"] == "https://example.com/docs"
    assert res["title"] == "Example Page"
    assert res["status"] == 200
    assert res["session_id"] == session.session_id
    assert "https://example.com/docs" in page.goto_calls


@pytest.mark.anyio
async def test_navigate_rejects_dangerous_scheme() -> None:
    """Phase 5C: Rejection of dangerous URL schemes (file://, javascript:, data:)."""
    policy = make_mock_policy()
    page = MockPage()
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    dangerous_urls = [
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "data:text/html,<h1>Pwned</h1>",
        "chrome://settings",
    ]

    for d_url in dangerous_urls:
        with pytest.raises(BrowserSecurityPolicyError) as exc_info:
            await ops.navigate(d_url, session_id=session.session_id)
        assert exc_info.value.error_code == BrowserPolicyErrorCode.UNSUPPORTED_SCHEME
        assert len(page.goto_calls) == 0


@pytest.mark.anyio
async def test_navigate_rejects_private_and_loopback() -> None:
    """Phase 5C: Rejection of private IP, loopback, and metadata destinations."""
    policy = make_mock_policy()
    page = MockPage()
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    forbidden = [
        ("http://127.0.0.1:8080", BrowserPolicyErrorCode.LOOPBACK_BLOCKED),
        ("http://localhost:80", BrowserPolicyErrorCode.LOOPBACK_BLOCKED),
        ("http://169.254.169.254/latest/meta-data", BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED),
        ("http://192.168.1.1/admin", BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED),
        ("http://10.0.0.5", BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED),
        ("http://172.16.0.1", BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED),
    ]

    for url, expected_code in forbidden:
        with pytest.raises(BrowserSecurityPolicyError) as exc_info:
            await ops.navigate(url, session_id=session.session_id)
        assert exc_info.value.error_code == expected_code
        assert len(page.goto_calls) == 0


@pytest.mark.anyio
async def test_navigate_unsafe_resolved_ip() -> None:
    """Phase 5C: Hostname resolving to private/loopback IP is blocked."""
    policy = make_mock_policy()
    page = MockPage()
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    # evil.com resolves to 192.168.1.100 (private)
    with pytest.raises(BrowserSecurityPolicyError) as exc_info:
        await ops.navigate("https://evil.com", session_id=session.session_id)
    assert exc_info.value.error_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP

    # rebinding.com resolves to 127.0.0.1 (loopback)
    with pytest.raises(BrowserSecurityPolicyError) as exc_info:
        await ops.navigate("https://rebinding.com", session_id=session.session_id)
    assert exc_info.value.error_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP


@pytest.mark.anyio
async def test_navigate_dns_resolution_failure() -> None:
    """Phase 5C: Fails closed when DNS resolution fails."""
    policy = BrowserSecurityPolicy(
        enforce_dns_resolution=True,
        dns_resolver=lambda host: [],  # DNS returns empty
    )
    page = MockPage()
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserSecurityPolicyError) as exc_info:
        await ops.navigate("https://nonexistent-domain.xyz", session_id=session.session_id)
    assert exc_info.value.error_code == BrowserPolicyErrorCode.DNS_RESOLUTION_FAILED


@pytest.mark.anyio
async def test_navigate_unsafe_redirect_rejection() -> None:
    """Phase 5C: Unsafe post-navigation redirect destination is rejected and remediated."""
    policy = make_mock_policy()
    page = MockPage()
    # Server redirects to private IP
    page.redirect_target = "http://192.168.1.1/internal"
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserSecurityPolicyError) as exc_info:
        await ops.navigate("https://example.com/redirect", session_id=session.session_id)

    assert exc_info.value.error_code == BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED
    # Safe remediation: page navigated away to about:blank
    assert "about:blank" in page.goto_calls


@pytest.mark.anyio
async def test_navigate_timeout_handling() -> None:
    """Phase 5C: Bounded navigation timeout raises BrowserTimeoutError."""
    policy = make_mock_policy()
    page = MockPage()
    page.fail_goto_timeout = True
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserTimeoutError):
        await ops.navigate(
            "https://example.com/slow", session_id=session.session_id, timeout_ms=5000
        )


@pytest.mark.anyio
async def test_navigate_route_blocked_by_client() -> None:
    """Phase 5C: Route aborted with ERR_BLOCKED_BY_CLIENT raises BrowserSecurityPolicyError."""
    policy = make_mock_policy()
    page = MockPage()
    page.fail_goto_blocked = True
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.navigate("https://example.com/blocked", session_id=session.session_id)


@pytest.mark.anyio
async def test_request_route_interceptor_enforcement() -> None:
    """Phase 5C: Route interceptor aborts unsafe subresources and allows safe ones."""
    policy = make_mock_policy()
    service = BrowserService(security_policy=policy)

    # 1. Unsafe subresource (metadata)
    bad_route = MockRoute()
    bad_request = MockRequest("http://169.254.169.254/secret.json")
    await service._handle_route_interception(bad_route, bad_request)
    assert bad_route.aborted is True
    assert bad_route.abort_reason == "blockedbyclient"
    assert bad_route.continued is False

    # 2. Unsafe subresource (private IP)
    private_route = MockRoute()
    private_request = MockRequest("http://10.0.0.1/script.js")
    await service._handle_route_interception(private_route, private_request)
    assert private_route.aborted is True
    assert private_route.abort_reason == "blockedbyclient"

    # 3. Safe subresource (example.com public)
    good_route = MockRoute()
    good_request = MockRequest("https://example.com/style.css")
    await service._handle_route_interception(good_route, good_request)
    assert good_route.continued is True
    assert good_route.aborted is False

    # 4. about:blank is permitted
    blank_route = MockRoute()
    blank_request = MockRequest("about:blank")
    await service._handle_route_interception(blank_route, blank_request)
    assert blank_route.continued is True


@pytest.mark.anyio
async def test_read_page_success_and_metadata() -> None:
    """Phase 5C: Safe page inspection extracts title, url, content, and bounds."""
    policy = make_mock_policy()
    page = MockPage(
        initial_url="https://example.com",
        initial_title="Test Title",
        body_text="Welcome to ECHO browser automation.",
    )
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    res = await ops.read_page(session_id=session.session_id)

    assert res["success"] is True
    assert res["operation"] == "browser_read_page"
    assert res["url"] == "https://example.com"
    assert res["title"] == "Test Title"
    assert "Welcome to ECHO browser automation." in res["content"]
    assert res["truncated"] is False
    assert res["content_length"] == len(res["content"])


@pytest.mark.anyio
async def test_read_page_oversized_content_bounding() -> None:
    """Phase 5C: Oversized content is safely bounded and flagged as truncated."""
    policy = make_mock_policy()
    huge_text = "A" * 60000
    page = MockPage(
        initial_url="https://example.com",
        body_text=huge_text,
    )
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    # Request max_length=500
    res = await ops.read_page(session_id=session.session_id, max_length=500)

    assert res["success"] is True
    assert res["content_length"] == 500
    assert len(res["content"]) == 500
    assert res["truncated"] is True


@pytest.mark.anyio
async def test_operations_closed_session_handling() -> None:
    """Phase 5C: Accessing a closed or inactive session raises BrowserSessionClosedError."""
    policy = make_mock_policy()
    page = MockPage()
    service, session = make_test_service(page, policy)
    await session.close()
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserSessionClosedError):
        await ops.navigate("https://example.com", session_id=session.session_id)

    with pytest.raises(BrowserSessionClosedError):
        await ops.read_page(session_id=session.session_id)


# ==============================================================================
# Phase 5D: Controlled Interaction Unit Tests
# ==============================================================================


@pytest.mark.anyio
async def test_click_safe_element_success() -> None:
    """Phase 5D: Safe click executes and reports structured output."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com")
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    res = await ops.click("button#next", session_id=session.session_id)

    assert res["success"] is True
    assert res["operation"] == "browser_click"
    assert res["selector"] == "button#next"
    assert res["navigation_occurred"] is False


@pytest.mark.anyio
async def test_click_missing_element_raises_error() -> None:
    """Phase 5D: Clicking non-existent element raises BrowserError."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com")
    page.element_counts["#does-not-exist"] = 0
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserError) as exc_info:
        await ops.click("#does-not-exist", session_id=session.session_id)
    assert "not found on the page" in str(exc_info.value)


@pytest.mark.anyio
async def test_click_rejects_invalid_selector() -> None:
    """Phase 5D: Invalid, oversized, or prohibited selector is rejected."""
    policy = make_mock_policy()
    page = MockPage()
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    # Empty selector
    with pytest.raises(BrowserError):
        await ops.click("", session_id=session.session_id)

    # Prohibited javascript: selector
    with pytest.raises(BrowserError):
        await ops.click("javascript:alert(1)", session_id=session.session_id)

    # Prohibited script tag selector
    with pytest.raises(BrowserError):
        await ops.click("<script>evil()</script>", session_id=session.session_id)

    # Oversized selector (> 500 chars)
    with pytest.raises(BrowserError):
        await ops.click("div." + "a" * 600, session_id=session.session_id)


@pytest.mark.anyio
async def test_click_detects_safe_navigation() -> None:
    """Phase 5D: Post-click navigation is detected and validated."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com/page1")
    page.click_nav_map["a.docs-link"] = "https://example.com/page2"
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    res = await ops.click("a.docs-link", session_id=session.session_id)

    assert res["success"] is True
    assert res["navigation_occurred"] is True
    assert res["url"] == "https://example.com/page2"


@pytest.mark.anyio
async def test_click_blocks_unsafe_post_click_navigation() -> None:
    """Phase 5D: Post-click navigation to unsafe private IP is blocked."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com")
    page.click_nav_map["a.evil-link"] = "http://192.168.1.1/admin"
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.click("a.evil-link", session_id=session.session_id)

    # Remediated away from unsafe destination
    assert "about:blank" in page.goto_calls


@pytest.mark.anyio
async def test_type_text_safe_input() -> None:
    """Phase 5D: Safe typing fills text and returns length."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com")
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    res = await ops.type_text(
        "input#search", "ECHO Operating System", session_id=session.session_id
    )

    assert res["success"] is True
    assert res["operation"] == "browser_type"
    assert res["selector"] == "input#search"
    assert res["text_length"] == len("ECHO Operating System")
    assert res["is_sensitive"] is False
    assert res["submitted"] is False


@pytest.mark.anyio
async def test_type_text_sensitive_secret_redaction() -> None:
    """Phase 5D: Sensitive typing never returns the secret text in result output."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com")
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    secret = "SuperSecretPassword123!"
    res = await ops.type_text(
        "input#password",
        secret,
        session_id=session.session_id,
        is_sensitive=True,
    )

    assert res["success"] is True
    assert res["is_sensitive"] is True
    assert res["text_length"] == len(secret)
    # The secret value MUST NOT be present anywhere in the returned result dictionary
    assert secret not in str(res)


@pytest.mark.anyio
async def test_type_text_oversized_input_rejection() -> None:
    """Phase 5D: Input exceeding maximum length is rejected."""
    policy = make_mock_policy()
    page = MockPage()
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    huge_text = "x" * 10001
    with pytest.raises(BrowserError) as exc_info:
        await ops.type_text("textarea#input", huge_text, session_id=session.session_id)
    assert "exceeds maximum allowed length" in str(exc_info.value)


@pytest.mark.anyio
async def test_type_text_submit_with_safe_navigation() -> None:
    """Phase 5D: Typing with submit=True presses Enter and validates navigation."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com/search")
    page.submit_nav_map["input#query"] = "https://example.com/results"
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    res = await ops.type_text(
        "input#query",
        "ECHO Architecture",
        session_id=session.session_id,
        submit=True,
    )

    assert res["success"] is True
    assert res["submitted"] is True
    assert res["url"] == "https://example.com/results"


@pytest.mark.anyio
async def test_type_text_submit_blocks_unsafe_navigation() -> None:
    """Phase 5D: Submit redirecting to unsafe private IP is blocked."""
    policy = make_mock_policy()
    page = MockPage(initial_url="https://example.com/login")
    page.submit_nav_map["input#login"] = "http://127.0.0.1:8080/internal"
    service, session = make_test_service(page, policy)
    ops = BrowserOperations(service=service, security_policy=policy)

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.type_text(
            "input#login",
            "admin",
            session_id=session.session_id,
            submit=True,
        )

    # Remediated away from unsafe destination
    assert "about:blank" in page.goto_calls
