"""Unit tests for ECHO Phase 5F: Browser Verification and Regression.

Deterministic, 100% offline unit tests covering:
- browser_open verification
- browser_close verification
- browser_navigate verification (success, failure, policy violation)
- browser_read_page verification (success, failure, truncation)
- browser_click verification (no nav, safe nav, blocked nav)
- browser_type verification (no submit, safe submit nav, blocked submit nav)
- browser_download verification (success, missing file, 0-byte, prohibited extension, outside sandbox, oversized, policy violation)
- browser_upload verification (success, safe nav, blocked nav, missing selector, failure)
- overall Request verification lifecycle (VERIFIED, NOT_VERIFIED, VERIFICATION_ERROR)
- fail-closed security properties on suspicious or policy-violating postconditions
"""

from pathlib import Path

import pytest

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.verification import (
    VerificationStatus,
)
from services.brain.verification import VerificationEngine
from services.browser.operations import BrowserOperations
from services.browser.policy import BrowserSecurityPolicy
from services.desktop.policy import DesktopSecurityPolicy


def make_mock_browser_policy() -> BrowserSecurityPolicy:
    """Create a mock BrowserSecurityPolicy with static DNS resolution for offline testing."""
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


@pytest.fixture
def browser_verification_setup(tmp_path: Path):
    """Fixture providing an isolated VerificationEngine with mock policies."""
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    desktop_policy = DesktopSecurityPolicy(
        authorized_roots=[sandbox_dir],
        include_default_roots=False,
    )
    browser_policy = make_mock_browser_policy()

    engine = VerificationEngine(
        desktop_policy=desktop_policy,
        browser_policy=browser_policy,
    )

    return {
        "engine": engine,
        "desktop_policy": desktop_policy,
        "browser_policy": browser_policy,
        "sandbox": sandbox_dir,
        "outside": tmp_path / "outside",
    }


# ==============================================================================
# 1. browser_open and browser_close Verification
# ==============================================================================


def test_verify_browser_open_success(browser_verification_setup):
    """Verify successful browser_open operation produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_open",
            "success": True,
            "session_id": "session-12345",
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert detail.operation == "browser_open"
    assert "session-12345" in detail.message


def test_verify_browser_open_failure(browser_verification_setup):
    """Verify failed browser_open operation produces NOT_VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_open",
            "success": False,
            "error": "Browser process failed to start",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "Browser process failed to start" in detail.observed


def test_verify_browser_open_missing_session_id(browser_verification_setup):
    """Verify browser_open without session_id produces NOT_VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_open",
            "success": True,
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "missing session identifier" in detail.message


def test_verify_browser_close_success(browser_verification_setup):
    """Verify successful browser_close operation produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_close",
            "success": True,
            "session_id": "session-12345",
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert detail.operation == "browser_close"
    assert "closure verified" in detail.message


def test_verify_browser_close_failure(browser_verification_setup):
    """Verify failed browser_close produces NOT_VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_close",
            "success": False,
            "error": "Session cleanup failed",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "Session cleanup failed" in detail.observed


# ==============================================================================
# 2. browser_navigate Verification
# ==============================================================================


def test_verify_browser_navigate_success(browser_verification_setup):
    """Verify browser_navigate with authorized URL produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_navigate",
            "success": True,
            "url": "https://example.com/docs",
            "status": 200,
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert detail.operation == "browser_navigate"
    assert "https://example.com/docs" in detail.message


def test_verify_browser_navigate_failure(browser_verification_setup):
    """Verify failed browser_navigate produces NOT_VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_navigate",
            "success": False,
            "error": "Navigation timeout",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "Navigation timeout" in detail.observed


def test_verify_browser_navigate_policy_violation(browser_verification_setup):
    """Verify browser_navigate to loopback/SSRF destination produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_navigate",
            "success": True,
            "url": "http://127.0.0.1:8080/admin",
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "violates browser security policy" in detail.message


# ==============================================================================
# 3. browser_read_page Verification
# ==============================================================================


def test_verify_browser_read_page_success(browser_verification_setup):
    """Verify browser_read_page extraction produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_read_page",
            "success": True,
            "content_length": 1500,
            "truncated": False,
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert "1500 characters extracted" in detail.message


def test_verify_browser_read_page_failure(browser_verification_setup):
    """Verify failed browser_read_page produces NOT_VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_read_page",
            "success": False,
            "error": "Page closed",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED


# ==============================================================================
# 4. browser_click Verification
# ==============================================================================


def test_verify_browser_click_without_navigation(browser_verification_setup):
    """Verify click without navigation produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_click",
            "success": True,
            "selector": "button#toggle",
            "navigation_occurred": False,
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert "button#toggle" in detail.message


def test_verify_browser_click_with_safe_navigation(browser_verification_setup):
    """Verify click with safe navigation produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_click",
            "success": True,
            "selector": "a#home",
            "navigation_occurred": True,
            "url": "https://example.com/home",
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert "https://example.com/home" in detail.message


def test_verify_browser_click_fails_if_navigates_to_blocked_url(browser_verification_setup):
    """Verify click navigating to SSRF/internal IP produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_click",
            "success": True,
            "selector": "a#internal",
            "navigation_occurred": True,
            "url": "http://169.254.169.254/latest/meta-data/",
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "violates browser security policy" in detail.message


# ==============================================================================
# 5. browser_type Verification
# ==============================================================================


def test_verify_browser_type_without_submit(browser_verification_setup):
    """Verify typing without submit produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_type",
            "success": True,
            "selector": "input#query",
            "text_length": 12,
            "submitted": False,
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert "12 characters" in detail.message


def test_verify_browser_type_with_safe_submit(browser_verification_setup):
    """Verify typing with submit navigating to safe URL produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_type",
            "success": True,
            "selector": "input#query",
            "text_length": 12,
            "submitted": True,
            "url": "https://example.com/search?q=hello",
        }
    )

    assert detail.status == VerificationStatus.VERIFIED


def test_verify_browser_type_fails_if_submit_navigates_to_blocked_url(browser_verification_setup):
    """Verify typing with submit navigating to loopback produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_type",
            "success": True,
            "selector": "input#query",
            "text_length": 12,
            "submitted": True,
            "url": "http://localhost:3000/api",
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "violates browser security policy" in detail.message


# ==============================================================================
# 6. browser_download Verification (Phase 5E/5F)
# ==============================================================================


def test_verify_browser_download_success(browser_verification_setup):
    """Verify valid download within sandbox produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    dest_file = sandbox / "report.pdf"
    dest_file.write_bytes(b"%PDF-1.4 sample content")

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": True,
            "destination_path": str(dest_file),
            "url": "https://example.com/report.pdf",
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert "report.pdf" in detail.message


def test_verify_browser_download_fails_when_file_missing_on_disk(browser_verification_setup):
    """Verify download claiming success but missing on disk produces NOT_VERIFIED."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    missing_file = sandbox / "phantom.pdf"
    if missing_file.exists():
        missing_file.unlink()

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": True,
            "destination_path": str(missing_file),
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "not found on disk" in detail.message


def test_verify_browser_download_fails_when_empty_file(browser_verification_setup):
    """Verify 0-byte download produces NOT_VERIFIED."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    empty_file = sandbox / "empty.pdf"
    empty_file.write_bytes(b"")

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": True,
            "destination_path": str(empty_file),
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "is empty (0 bytes)" in detail.message


def test_verify_browser_download_fails_when_outside_sandbox(browser_verification_setup):
    """Verify download outside sandbox produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    outside_dir = browser_verification_setup["outside"]
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "loot.pdf"
    outside_file.write_bytes(b"data")

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": True,
            "destination_path": str(outside_file),
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "violates desktop security policy" in detail.message


def test_verify_browser_download_fails_when_prohibited_extension(browser_verification_setup):
    """Verify download with executable extension (.exe) produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    exe_file = sandbox / "malware.exe"
    exe_file.write_bytes(b"MZ123")

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": True,
            "destination_path": str(exe_file),
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "prohibited executable extension '.exe'" in detail.message


def test_verify_browser_download_fails_when_oversized(browser_verification_setup):
    """Verify download exceeding size limit produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    dest_file = sandbox / "large.bin"
    dest_file.write_bytes(b"A" * 100)

    # Temporarily set max download limit to 50 bytes
    orig_limit = BrowserOperations.MAX_DOWNLOAD_SIZE_BYTES
    try:
        BrowserOperations.MAX_DOWNLOAD_SIZE_BYTES = 50
        detail = engine._verify_operation_postcondition(
            {
                "operation": "browser_download",
                "success": True,
                "destination_path": str(dest_file),
            }
        )

        assert detail.status == VerificationStatus.VERIFICATION_ERROR
        assert "exceeds maximum limit" in detail.message
    finally:
        BrowserOperations.MAX_DOWNLOAD_SIZE_BYTES = orig_limit


def test_verify_browser_download_fails_when_url_violates_policy(browser_verification_setup):
    """Verify download from SSRF/loopback URL produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    dest_file = sandbox / "valid.pdf"
    dest_file.write_bytes(b"PDF content")

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": True,
            "destination_path": str(dest_file),
            "url": "http://127.0.0.1:8080/secret.pdf",
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "violates browser security policy" in detail.message


def test_verify_browser_download_fails_when_execution_failed(browser_verification_setup):
    """Verify download execution failure produces NOT_VERIFIED or VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]

    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_download",
            "success": False,
            "error": "Download expectation timed out",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "Download expectation timed out" in detail.message


# ==============================================================================
# 7. browser_upload Verification (Phase 5E/5F)
# ==============================================================================


def test_verify_browser_upload_success(browser_verification_setup):
    """Verify successful upload produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_upload",
            "success": True,
            "selector": "input#avatar",
            "file_name": "photo.png",
            "file_size": 2048,
            "navigation_occurred": False,
        }
    )

    assert detail.status == VerificationStatus.VERIFIED
    assert "photo.png" in detail.message
    assert "input#avatar" in detail.message


def test_verify_browser_upload_with_safe_navigation(browser_verification_setup):
    """Verify upload triggering safe navigation produces VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_upload",
            "success": True,
            "selector": "input#avatar",
            "file_name": "photo.png",
            "file_size": 2048,
            "navigation_occurred": True,
            "url": "https://example.com/profile",
        }
    )

    assert detail.status == VerificationStatus.VERIFIED


def test_verify_browser_upload_fails_when_navigation_violates_policy(browser_verification_setup):
    """Verify upload triggering SSRF navigation produces VERIFICATION_ERROR."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_upload",
            "success": True,
            "selector": "input#avatar",
            "file_name": "photo.png",
            "file_size": 2048,
            "navigation_occurred": True,
            "url": "http://10.0.0.1/upload_receiver",
        }
    )

    assert detail.status == VerificationStatus.VERIFICATION_ERROR
    assert "violates browser security policy" in detail.message


def test_verify_browser_upload_missing_selector(browser_verification_setup):
    """Verify upload without selector produces NOT_VERIFIED detail."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_upload",
            "success": True,
            "selector": "",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED
    assert "missing selector" in detail.message


def test_verify_browser_upload_fails_when_execution_failed(browser_verification_setup):
    """Verify upload execution failure produces appropriate status."""
    engine = browser_verification_setup["engine"]
    detail = engine._verify_operation_postcondition(
        {
            "operation": "browser_upload",
            "success": False,
            "error": "Element not found on the page: input#avatar",
        }
    )

    assert detail.status == VerificationStatus.NOT_VERIFIED


# ==============================================================================
# 8. Request-Level Verification Lifecycle & Fail-Closed Integrity
# ==============================================================================


def test_verification_engine_verify_request_success_flow(browser_verification_setup):
    """Verify end-to-end Request verification for browser actions."""
    engine = browser_verification_setup["engine"]
    sandbox = browser_verification_setup["sandbox"]

    pdf_file = sandbox / "paper.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 content")

    req = Request(user_input="Download research paper")
    exec_result = ExecutionResult(
        success=True,
        result=[
            {
                "operation": "browser_navigate",
                "success": True,
                "url": "https://example.com/paper",
                "status": 200,
            },
            {
                "operation": "browser_download",
                "success": True,
                "destination_path": str(pdf_file),
                "url": "https://example.com/paper.pdf",
            },
        ],
    )

    verif_result = engine.verify(req, exec_result)
    assert verif_result.success is True
    assert verif_result.status == VerificationStatus.VERIFIED
    assert len(verif_result.details) == 2
    assert all(d.status == VerificationStatus.VERIFIED for d in verif_result.details)


def test_verification_engine_verify_request_fails_closed_on_security_error(
    browser_verification_setup,
):
    """Verify Request status fails closed to FAILED if any browser step violates policy."""
    engine = browser_verification_setup["engine"]

    req = Request(user_input="Suspicious navigation")
    exec_result = ExecutionResult(
        success=True,
        result=[
            {
                "operation": "browser_navigate",
                "success": True,
                "url": "http://127.0.0.1:8080/evil",
            },
        ],
    )

    verif_result = engine.verify(req, exec_result)
    assert verif_result.success is False
    assert verif_result.status == VerificationStatus.VERIFICATION_ERROR
    assert req.status == RequestStatus.FAILED
    assert "violates browser security policy" in req.error
