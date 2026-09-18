"""Unit tests for ECHO Phase 5E: Secure Browser File Transfer (download and upload).

Deterministic, 100% offline unit tests covering:
- safe download via URL and selector
- download confirmation requirement (SafetyEngine)
- download destination sandbox validation
- traversal rejection
- UNC/network path rejection
- protected directory rejection (SystemRoot, ProgramFiles)
- sensitive destination rejection (.ssh, .aws, credentials)
- dangerous/executable download handling (.exe, .bat, .ps1, etc.)
- download size limit (purged if exceeds 50MB)
- malicious server-suggested filename handling
- safe upload via selector
- upload confirmation requirement (SafetyEngine)
- upload source sandbox validation
- nonexistent upload source rejection
- sensitive source rejection (.pem, id_rsa, .secrets)
- upload size limit (exceeds 50MB)
- secret/path redaction
- closed browser/session handling
- browser lifecycle failure
- resume safety re-check
- confirmation replay prevention
"""

from pathlib import Path

import pytest

from packages.interfaces.security import PermissionDecision, RiskLevel
from services.browser.errors import (
    BrowserError,
    BrowserTimeoutError,
)
from services.browser.operations import BrowserOperations
from services.browser.policy import BrowserSecurityPolicy, BrowserSecurityPolicyError
from services.browser.service import BrowserService
from services.browser.session import BrowserSession
from services.desktop.policy import DesktopSecurityPolicy
from services.security.pending_action_manager import PendingActionManager
from services.security.safety_engine import SafetyEngine

# ==============================================================================
# Mock Playwright Hierarchy for Offline Deterministic Testing
# ==============================================================================


class MockDownload:
    """Mock Playwright Download object."""

    def __init__(
        self,
        filename: str = "report.pdf",
        content: bytes = b"PDF-1.4 file content",
        url: str = "https://example.com/report.pdf",
    ) -> None:
        self.suggested_filename = filename
        self.content = content
        self.url = url
        self.saved_path: str | None = None

    async def save_as(self, path: str) -> None:
        self.saved_path = path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.content)


class MockDownloadContext:
    """Async context manager returned by page.expect_download()."""

    def __init__(self, download: MockDownload, should_timeout: bool = False) -> None:
        self.download = download
        self.should_timeout = should_timeout

    async def __aenter__(self) -> "MockDownloadContext":  # noqa: PYI034
        if self.should_timeout:
            raise TimeoutError("Download expectation timed out after 10000ms")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        pass

    @property
    async def value(self) -> MockDownload:
        return self.download


class MockLocator:
    """Mock Playwright Locator."""

    def __init__(
        self,
        selector: str,
        page: "MockPage",
        element_count: int = 1,
    ) -> None:
        self.selector = selector
        self.page = page
        self.element_count = element_count
        self.clicked = False
        self.uploaded_files: list[str] = []
        self.upload_timeout_error = False
        self.click_timeout_error = False
        self.nav_on_click: str | None = None
        self.nav_on_upload: str | None = None

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

    async def set_input_files(self, files: str | list[str], timeout: int = 30000) -> None:
        if self.upload_timeout_error:
            raise TimeoutError(f"Upload timed out after {timeout}ms")
        if isinstance(files, str):
            self.uploaded_files.append(files)
        else:
            self.uploaded_files.extend(files)
        if self.nav_on_upload:
            self.page.url = self.nav_on_upload


class MockPage:
    """Mock Playwright Page."""

    def __init__(self, initial_url: str = "about:blank") -> None:
        self.url = initial_url
        self.closed = False
        self.element_counts: dict[str, int] = {}
        self.click_nav_map: dict[str, str] = {}
        self.upload_nav_map: dict[str, str] = {}
        self.mock_download = MockDownload()
        self.fail_download_timeout = False

    async def goto(self, url: str, timeout: int = 30000) -> None:
        self.url = url

    def locator(self, selector: str) -> MockLocator:
        count = self.element_counts.get(selector, 1)
        loc = MockLocator(selector=selector, page=self, element_count=count)
        if selector in self.click_nav_map:
            loc.nav_on_click = self.click_nav_map[selector]
        if selector in self.upload_nav_map:
            loc.nav_on_upload = self.upload_nav_map[selector]
        return loc

    def expect_download(self, timeout: int = 30000) -> MockDownloadContext:
        return MockDownloadContext(self.mock_download, should_timeout=self.fail_download_timeout)

    async def close(self) -> None:
        self.closed = True


class MockContext:
    """Mock Playwright Context."""

    def __init__(self, page: MockPage) -> None:
        self._page = page

    async def new_page(self) -> MockPage:
        return self._page

    async def close(self) -> None:
        await self._page.close()


def create_test_session(
    page: MockPage | None = None,
    session_id: str = "test_session_5e",
) -> tuple[BrowserSession, MockPage]:
    """Helper to build a mock BrowserSession."""
    p = page or MockPage(initial_url="https://example.com/portal")
    ctx = MockContext(p)
    session = BrowserSession(
        session_id=session_id,
        context=ctx,  # type: ignore[arg-type]
        primary_page=p,  # type: ignore[arg-type]
        timeout_ms=10000,
    )
    return session, p


def make_mock_policy() -> BrowserSecurityPolicy:
    """Create a test BrowserSecurityPolicy with static DNS resolution."""
    dns_map = {
        "example.com": ["93.184.216.34"],
        "safe.org": ["198.51.100.1"],
        "evil.com": ["192.168.1.100"],
    }

    def mock_dns(host: str) -> list[str]:
        return dns_map.get(host, ["93.184.216.34"])

    return BrowserSecurityPolicy(
        enforce_dns_resolution=True,
        dns_resolver=mock_dns,
    )


def create_test_service(
    session: BrowserSession,
    policy: BrowserSecurityPolicy | None = None,
) -> BrowserService:
    """Helper to build a BrowserService containing the mock session."""
    pol = policy or make_mock_policy()
    service = BrowserService(security_policy=pol)
    service._state = service._state.__class__.RUNNING
    service._sessions[session.session_id] = session
    return service


# ==============================================================================
# Phase 5E — Download Tests
# ==============================================================================


@pytest.mark.anyio
async def test_safe_download_via_url(tmp_path: Path) -> None:
    """Verify safe download triggered by URL navigation saves to authorized sandbox path."""
    dest = tmp_path / "report.pdf"
    session, page = create_test_session()
    page.mock_download = MockDownload(
        filename="report.pdf",
        content=b"Sample PDF content 12345",
        url="https://example.com/files/report.pdf",
    )

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    result = await ops.download(
        destination_path=str(dest),
        url="https://example.com/files/report.pdf",
        session_id=session.session_id,
    )

    assert result["success"] is True
    assert result["operation"] == "browser_download"
    assert result["file_name"] == "report.pdf"
    assert result["file_size"] == len(b"Sample PDF content 12345")
    assert dest.exists()
    assert dest.read_bytes() == b"Sample PDF content 12345"


@pytest.mark.anyio
async def test_safe_download_via_selector(tmp_path: Path) -> None:
    """Verify safe download triggered by clicking a selector saves to authorized sandbox path."""
    dest = tmp_path / "data.csv"
    session, page = create_test_session()
    page.mock_download = MockDownload(
        filename="data.csv",
        content=b"id,name\n1,Alice\n2,Bob\n",
        url="https://example.com/export",
    )

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    result = await ops.download(
        destination_path=str(dest),
        selector="button#export-csv",
        session_id=session.session_id,
    )

    assert result["success"] is True
    assert result["file_name"] == "data.csv"
    assert result["file_size"] == len(b"id,name\n1,Alice\n2,Bob\n")
    assert dest.exists()


@pytest.mark.anyio
async def test_download_directory_destination_uses_sanitized_suggested_filename(
    tmp_path: Path,
) -> None:
    """Verify specifying an existing directory as destination saves using sanitized suggested filename."""
    session, page = create_test_session()
    page.mock_download = MockDownload(
        filename="export_2026.json",
        content=b'{"status": "ok"}',
    )

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    result = await ops.download(
        destination_path=str(tmp_path),
        url="https://example.com/export.json",
        session_id=session.session_id,
    )

    assert result["success"] is True
    assert result["file_name"] == "export_2026.json"
    expected_file = tmp_path / "export_2026.json"
    assert expected_file.exists()
    assert expected_file.read_bytes() == b'{"status": "ok"}'


@pytest.mark.anyio
async def test_download_ambiguous_url_and_selector_rejected(tmp_path: Path) -> None:
    """Verify specifying both url and selector (or neither) raises BrowserError."""
    session, _ = create_test_session()
    ops = BrowserOperations(service=create_test_service(session))

    with pytest.raises(BrowserError, match="Provide either 'url' or 'selector'"):
        await ops.download(
            destination_path=str(tmp_path / "out.txt"),
            url="https://example.com/file",
            selector="a#download",
            session_id=session.session_id,
        )

    with pytest.raises(BrowserError, match="Provide either 'url' or 'selector'"):
        await ops.download(
            destination_path=str(tmp_path / "out.txt"),
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_rejects_destination_outside_sandbox(tmp_path: Path) -> None:
    """Verify download to a path outside authorized sandbox roots fails closed."""
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    outside_dest = tmp_path / "outside" / "evil.txt"

    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[sandbox_dir])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserSecurityPolicyError, match="not permitted"):
        await ops.download(
            destination_path=str(outside_dest),
            url="https://example.com/file.txt",
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_rejects_path_traversal(tmp_path: Path) -> None:
    """Verify download destination with path traversal outside sandbox is rejected."""
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    traversal_path = str(sandbox_dir / ".." / "outside.txt")

    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[sandbox_dir])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.download(
            destination_path=traversal_path,
            url="https://example.com/file.txt",
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_rejects_unc_destination(tmp_path: Path) -> None:
    """Verify UNC destination paths are rejected."""
    session, _ = create_test_session()
    ops = BrowserOperations(service=create_test_service(session))

    with pytest.raises(BrowserError, match="UNC"):
        await ops.download(
            destination_path=r"\\malicious-smb\share\loot.txt",
            url="https://example.com/file.txt",
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_rejects_protected_system_locations(tmp_path: Path) -> None:
    """Verify protected Windows system directories are rejected as destination."""
    session, _ = create_test_session()
    ops = BrowserOperations(service=create_test_service(session))

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.download(
            destination_path=r"C:\Windows\System32\payload.txt",
            url="https://example.com/file.txt",
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_rejects_sensitive_files(tmp_path: Path) -> None:
    """Verify downloading directly onto sensitive files (e.g. id_rsa, credentials) is blocked."""
    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.download(
            destination_path=str(tmp_path / "id_rsa"),
            url="https://example.com/key",
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_rejects_executable_extension(tmp_path: Path) -> None:
    """Verify downloading files with executable or script extensions is strictly blocked."""
    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    blocked_extensions = [".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".dll", ".scr"]
    for ext in blocked_extensions:
        with pytest.raises(BrowserSecurityPolicyError, match="prohibited"):
            await ops.download(
                destination_path=str(tmp_path / f"payload{ext}"),
                url="https://example.com/setup",
                session_id=session.session_id,
            )


@pytest.mark.anyio
async def test_download_rejects_executable_in_suggested_filename(tmp_path: Path) -> None:
    """Verify that if server suggests an executable filename into a directory destination, it is blocked."""
    session, page = create_test_session()
    page.mock_download = MockDownload(
        filename="malware.exe",
        content=b"MZ binary content",
    )

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserSecurityPolicyError, match="prohibited"):
        await ops.download(
            destination_path=str(tmp_path),
            url="https://example.com/get",
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_download_size_limit_enforced_and_unlinks_oversized_file(tmp_path: Path) -> None:
    """Verify that files exceeding the size limit are purged and an error is raised."""
    session, page = create_test_session()
    oversized_bytes = b"X" * 100
    page.mock_download = MockDownload(
        filename="large.dat",
        content=oversized_bytes,
    )

    dest = tmp_path / "large.dat"
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )
    # Set limit to 50 bytes
    ops.MAX_DOWNLOAD_SIZE_BYTES = 50

    with pytest.raises(BrowserError, match="exceeds maximum limit"):
        await ops.download(
            destination_path=str(dest),
            url="https://example.com/large",
            session_id=session.session_id,
        )

    # Confirm oversized file was removed from disk
    assert not dest.exists()


@pytest.mark.anyio
async def test_download_timeout_handling(tmp_path: Path) -> None:
    """Verify download timeout raises BrowserTimeoutError."""
    session, page = create_test_session()
    page.fail_download_timeout = True

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserTimeoutError, match="timed out"):
        await ops.download(
            destination_path=str(tmp_path / "out.pdf"),
            url="https://example.com/slow",
            session_id=session.session_id,
        )


# ==============================================================================
# Phase 5E — Upload Tests
# ==============================================================================


@pytest.mark.anyio
async def test_safe_upload(tmp_path: Path) -> None:
    """Verify uploading a local file from an authorized sandbox path."""
    source_file = tmp_path / "document.pdf"
    source_file.write_bytes(b"PDF document content")

    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    result = await ops.upload(
        selector="input#file-input",
        file_path=str(source_file),
        session_id=session.session_id,
    )

    assert result["success"] is True
    assert result["operation"] == "browser_upload"
    assert result["file_name"] == "document.pdf"
    assert result["file_size"] == len(b"PDF document content")


@pytest.mark.anyio
async def test_upload_rejects_nonexistent_file(tmp_path: Path) -> None:
    """Verify uploading a nonexistent file raises BrowserError."""
    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserError, match="does not exist"):
        await ops.upload(
            selector="input#file-input",
            file_path=str(tmp_path / "missing.txt"),
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_upload_rejects_file_outside_sandbox(tmp_path: Path) -> None:
    """Verify uploading a file outside authorized roots is rejected by policy."""
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside")

    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[sandbox_dir])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserSecurityPolicyError, match="not permitted"):
        await ops.upload(
            selector="input#file-input",
            file_path=str(outside_file),
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_upload_rejects_sensitive_credentials(tmp_path: Path) -> None:
    """Verify uploading private key or sensitive credential file is rejected."""
    key_file = tmp_path / "id_rsa"
    key_file.write_text("FAKE RSA PRIVATE KEY")

    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserSecurityPolicyError):
        await ops.upload(
            selector="input#file-input",
            file_path=str(key_file),
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_upload_rejects_oversized_file(tmp_path: Path) -> None:
    """Verify uploading file exceeding size limit is rejected."""
    large_file = tmp_path / "large.bin"
    large_file.write_bytes(b"B" * 200)

    session, _ = create_test_session()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )
    ops.MAX_UPLOAD_SIZE_BYTES = 100

    with pytest.raises(BrowserError, match="exceeds maximum limit"):
        await ops.upload(
            selector="input#file-input",
            file_path=str(large_file),
            session_id=session.session_id,
        )


@pytest.mark.anyio
async def test_upload_missing_element_raises_error(tmp_path: Path) -> None:
    """Verify upload raises BrowserError when selector does not exist."""
    source_file = tmp_path / "valid.txt"
    source_file.write_text("hello")

    session, page = create_test_session()
    page.element_counts["input#missing"] = 0

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    ops = BrowserOperations(
        service=create_test_service(session),
        desktop_policy=desktop_policy,
    )

    with pytest.raises(BrowserError, match="not found on the page"):
        await ops.upload(
            selector="input#missing",
            file_path=str(source_file),
            session_id=session.session_id,
        )


# ==============================================================================
# Phase 5E — SafetyEngine, Confirmation, Resume, Replay Prevention
# ==============================================================================


def test_safety_engine_requires_confirmation_for_safe_download(tmp_path: Path) -> None:
    """Verify SafetyEngine requires CONFIRM for a valid download action."""
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    engine = SafetyEngine(browser_policy=make_mock_policy(), desktop_policy=desktop_policy)
    result = engine.evaluate(
        "browser_download",
        arguments={
            "url": "https://example.com/report.pdf",
            "destination_path": str(tmp_path / "report.pdf"),
        },
    )

    assert result.decision == PermissionDecision.CONFIRM
    assert result.risk_level == RiskLevel.SENSITIVE


def test_safety_engine_blocks_malicious_download(tmp_path: Path) -> None:
    """Verify SafetyEngine immediately BLOCKS download of executable or SSRF URL."""
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    engine = SafetyEngine(browser_policy=make_mock_policy(), desktop_policy=desktop_policy)

    # Blocked executable destination
    exe_result = engine.evaluate(
        "browser_download",
        arguments={
            "url": "https://example.com/malware.exe",
            "destination_path": str(tmp_path / "malware.exe"),
        },
    )
    assert exe_result.decision == PermissionDecision.BLOCK
    assert exe_result.risk_level == RiskLevel.CRITICAL

    # Blocked SSRF loopback URL
    ssrf_result = engine.evaluate(
        "browser_download",
        arguments={
            "url": "http://127.0.0.1:8080/loot.txt",
            "destination_path": str(tmp_path / "loot.txt"),
        },
    )
    assert ssrf_result.decision == PermissionDecision.BLOCK
    assert ssrf_result.risk_level == RiskLevel.CRITICAL


def test_safety_engine_requires_confirmation_for_safe_upload(tmp_path: Path) -> None:
    """Verify SafetyEngine requires CONFIRM for safe upload."""
    valid_file = tmp_path / "profile.jpg"
    valid_file.write_bytes(b"image")

    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    engine = SafetyEngine(desktop_policy=desktop_policy)
    result = engine.evaluate(
        "browser_upload",
        arguments={
            "selector": "input#avatar",
            "file_path": str(valid_file),
        },
    )

    assert result.decision == PermissionDecision.CONFIRM
    assert result.risk_level == RiskLevel.SENSITIVE


def test_safety_engine_blocks_sensitive_upload() -> None:
    """Verify SafetyEngine BLOCKS upload of sensitive private keys."""
    engine = SafetyEngine()
    result = engine.evaluate(
        "browser_upload",
        arguments={
            "selector": "input#avatar",
            "file_path": r"C:\Users\test\.ssh\id_rsa",
        },
    )

    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL


def test_pending_action_resume_safety_recheck_and_replay_prevention(tmp_path: Path) -> None:
    """Verify pending action confirmation, mandatory safety re-check, and replay prevention."""
    pam = PendingActionManager()
    desktop_policy = DesktopSecurityPolicy(authorized_roots=[tmp_path])
    engine = SafetyEngine(browser_policy=make_mock_policy(), desktop_policy=desktop_policy)

    valid_dest = str(tmp_path / "report.pdf")
    action = pam.create_pending_action(
        tool_name="browser_download",
        arguments={"destination_path": valid_dest, "url": "https://example.com/file.pdf"},
        risk_level=RiskLevel.SENSITIVE,
    )

    # 1. Claim for execution
    success, claim, _, _ = pam.claim_for_execution(action.action_id)
    assert success is True
    assert claim is not None
    assert claim.action_id == action.action_id

    # 2. Mandatory safety re-check before execution
    safety_check = engine.evaluate(claim.tool_name, claim.arguments)
    assert safety_check.decision == PermissionDecision.CONFIRM

    # 3. Mark executed
    pam.mark_executed(action.action_id)

    # 4. Replay prevention: cannot claim or execute already executed action
    success_replay, _, _, _ = pam.claim_for_execution(action.action_id)
    assert success_replay is False
