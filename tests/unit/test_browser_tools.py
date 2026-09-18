"""Unit tests for ECHO Browser Tools Integration (Phase 5C + Phase 5D).

Tests:
- Tool registry and tool router integration for browser tools
- SafetyEngine risk classification and permission decisions
- Confirmation boundary triggers (submit, sensitive keywords, password fields)
- Pending action creation and resume via ExecutionEngine
- Mandatory safety re-checks and replay prevention
- VerificationEngine post-condition verifications
"""

import pytest

from packages.common.tool_registry import tool_registry
from packages.interfaces.execution import ExecutionResult
from packages.interfaces.pending_action import ConfirmationStatus
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.verification import VerificationStatus
from services.brain.execution import ExecutionEngine
from services.brain.tool_router import ToolRouter
from services.brain.tools.browser_tools import (
    BrowserClickTool,
    BrowserNavigateTool,
    BrowserReadPageTool,
    BrowserTypeTool,
)
from services.brain.verification import VerificationEngine
from services.browser.operations import browser_operations
from services.browser.policy import BrowserSecurityPolicy
from services.security.pending_action_manager import PendingActionManager
from services.security.safety_engine import SafetyEngine

# ==============================================================================
# 1. Tool Registry & Router Integration
# ==============================================================================


def test_browser_tools_registered_in_tool_registry() -> None:
    """Verify all browser tools are present in tool_registry with valid definitions."""
    expected_tools = [
        "browser_navigate",
        "browser_read_page",
        "browser_click",
        "browser_type",
    ]

    for tool_name in expected_tools:
        tool = tool_registry.get(tool_name)
        assert tool is not None, f"Tool '{tool_name}' should be registered."
        definition = getattr(tool, "definition", None)
        assert definition is not None
        assert definition.name == tool_name
        assert len(definition.parameters) > 0 or tool_name == "browser_read_page"


def test_tool_router_knows_browser_tools() -> None:
    """Verify ToolRouter recognizes browser tools."""
    router = ToolRouter()
    assert router.is_tool_registered("browser_navigate") is True
    assert router.is_tool_registered("browser_read_page") is True
    assert router.is_tool_registered("browser_click") is True
    assert router.is_tool_registered("browser_type") is True


# ==============================================================================
# 2. SafetyEngine & RiskClassifier Integration
# ==============================================================================


def test_safety_engine_browser_read_page_is_safe() -> None:
    """browser_read_page is classified as SAFE and ALLOW."""
    engine = SafetyEngine()
    result = engine.evaluate("browser_read_page")
    assert result.decision == PermissionDecision.ALLOW
    assert result.risk_level == RiskLevel.SAFE


def test_safety_engine_browser_navigate_allowed_url() -> None:
    """browser_navigate to valid public URL is ALLOW."""
    engine = SafetyEngine()
    result = engine.evaluate("browser_navigate", arguments={"url": "https://example.com"})
    assert result.decision == PermissionDecision.ALLOW
    assert result.risk_level == RiskLevel.SAFE


def test_safety_engine_browser_navigate_blocks_loopback() -> None:
    """browser_navigate to loopback/private target is BLOCKED."""
    engine = SafetyEngine()
    blocked_targets = [
        "http://127.0.0.1:8080",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.1/router",
        "file:///C:/secrets.txt",
    ]
    for target in blocked_targets:
        result = engine.evaluate("browser_navigate", arguments={"url": target})
        assert result.decision == PermissionDecision.BLOCK
        assert result.risk_level == RiskLevel.CRITICAL


def test_safety_engine_browser_navigate_confirms_unlisted_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """browser_navigate confirms unlisted domains when confirm_unlisted_domains=True."""
    strict_policy = BrowserSecurityPolicy(
        allowed_domains=["allowed.example.com"],
        confirm_unlisted_domains=True,
    )
    monkeypatch.setattr("services.browser.policy.browser_security_policy", strict_policy)

    engine = SafetyEngine()
    result = engine.evaluate("browser_navigate", arguments={"url": "https://other.org"})
    assert result.decision == PermissionDecision.CONFIRM
    assert result.risk_level == RiskLevel.SENSITIVE


def test_safety_engine_browser_click_safe_vs_sensitive() -> None:
    """browser_click is ALLOW for regular clicks, CONFIRM for state-changing/submit clicks."""
    engine = SafetyEngine()

    # Regular benign click
    safe_click = engine.evaluate("browser_click", arguments={"selector": "div.tab-header"})
    assert safe_click.decision == PermissionDecision.ALLOW
    assert safe_click.risk_level == RiskLevel.MODERATE

    # Explicit is_submit=True
    submit_click = engine.evaluate(
        "browser_click",
        arguments={"selector": "button.action", "is_submit": True},
    )
    assert submit_click.decision == PermissionDecision.CONFIRM
    assert submit_click.risk_level == RiskLevel.SENSITIVE

    # Sensitive action selector keywords
    sensitive_selectors = [
        "button#submit-payment",
        "a.delete-account",
        "button.buy-now",
        "button.confirm-transfer",
        "a#login-btn",
    ]
    for sel in sensitive_selectors:
        res = engine.evaluate("browser_click", arguments={"selector": sel})
        assert res.decision == PermissionDecision.CONFIRM
        assert res.risk_level == RiskLevel.SENSITIVE


def test_safety_engine_browser_type_safe_vs_sensitive() -> None:
    """browser_type is ALLOW for normal typing, CONFIRM for sensitive secrets or submit."""
    engine = SafetyEngine()

    # Normal typing without submit
    normal_type = engine.evaluate(
        "browser_type",
        arguments={"selector": "input#search", "text": "documentation"},
    )
    assert normal_type.decision == PermissionDecision.ALLOW
    assert normal_type.risk_level == RiskLevel.MODERATE

    # Sensitive secret flag
    sensitive_type = engine.evaluate(
        "browser_type",
        arguments={"selector": "input#secret", "text": "1234", "is_sensitive": True},
    )
    assert sensitive_type.decision == PermissionDecision.CONFIRM
    assert sensitive_type.risk_level == RiskLevel.SENSITIVE

    # Submit flag
    submit_type = engine.evaluate(
        "browser_type",
        arguments={"selector": "input#search", "text": "docs", "submit": True},
    )
    assert submit_type.decision == PermissionDecision.CONFIRM
    assert submit_type.risk_level == RiskLevel.SENSITIVE

    # Sensitive field selector keywords
    sensitive_fields = [
        "input#password",
        "input[name='user_pass']",
        "input#security_pin",
        "input#credit_card_number",
        "input#auth_token",
    ]
    for field_sel in sensitive_fields:
        res = engine.evaluate(
            "browser_type",
            arguments={"selector": field_sel, "text": "val"},
        )
        assert res.decision == PermissionDecision.CONFIRM
        assert res.risk_level == RiskLevel.SENSITIVE


# ==============================================================================
# 3. VerificationEngine Integration
# ==============================================================================


def test_verify_browser_navigate_success() -> None:
    """VerificationEngine verifies successful navigation to compliant URL."""
    engine = VerificationEngine()
    req = Request(user_input="Navigate to docs")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "browser_navigate",
            "url": "https://example.com/docs",
            "status": 200,
            "success": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


def test_verify_browser_navigate_blocked_destination_fails_verification() -> None:
    """VerificationEngine returns VERIFICATION_ERROR if navigation reached unsafe IP."""
    engine = VerificationEngine()
    req = Request(user_input="Navigate")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "browser_navigate",
            "url": "http://127.0.0.1:8000/internal",
            "status": 200,
            "success": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.VERIFICATION_ERROR


def test_verify_browser_read_page_success() -> None:
    """VerificationEngine verifies read_page result."""
    engine = VerificationEngine()
    req = Request(user_input="Read page")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "browser_read_page",
            "url": "https://example.com",
            "title": "Example",
            "content": "Sample content",
            "content_length": 14,
            "truncated": False,
            "success": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


def test_verify_browser_click_success_and_nav() -> None:
    """VerificationEngine verifies click without navigation and with safe navigation."""
    engine = VerificationEngine()

    # Click without nav
    req1 = Request(user_input="Click button")
    exec_res1 = ExecutionResult(
        success=True,
        result={
            "operation": "browser_click",
            "selector": "button#next",
            "url": "https://example.com",
            "navigation_occurred": False,
            "success": True,
        },
    )
    v_res1 = engine.verify(req1, exec_res1)
    assert v_res1.success is True
    assert v_res1.status == VerificationStatus.VERIFIED

    # Click with safe nav
    req2 = Request(user_input="Click link")
    exec_res2 = ExecutionResult(
        success=True,
        result={
            "operation": "browser_click",
            "selector": "a#home",
            "url": "https://example.com/home",
            "navigation_occurred": True,
            "success": True,
        },
    )
    v_res2 = engine.verify(req2, exec_res2)
    assert v_res2.success is True
    assert v_res2.status == VerificationStatus.VERIFIED

    # Click with unsafe nav
    req3 = Request(user_input="Click link")
    exec_res3 = ExecutionResult(
        success=True,
        result={
            "operation": "browser_click",
            "selector": "a#evil",
            "url": "http://192.168.1.1/admin",
            "navigation_occurred": True,
            "success": True,
        },
    )
    v_res3 = engine.verify(req3, exec_res3)
    assert v_res3.success is False
    assert v_res3.status == VerificationStatus.VERIFICATION_ERROR


def test_verify_browser_type_success() -> None:
    """VerificationEngine verifies text input."""
    engine = VerificationEngine()
    req = Request(user_input="Type query")
    exec_res = ExecutionResult(
        success=True,
        result={
            "operation": "browser_type",
            "selector": "input#search",
            "text_length": 15,
            "submitted": False,
            "success": True,
        },
    )

    v_res = engine.verify(req, exec_res)
    assert v_res.success is True
    assert v_res.status == VerificationStatus.VERIFIED


# ==============================================================================
# 4. Confirmation & Execution Pipeline Integration
# ==============================================================================


def test_execution_engine_requires_confirmation_for_sensitive_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ExecutionEngine creates pending action when a sensitive browser action is executed."""
    pam = PendingActionManager()
    safety = SafetyEngine()
    router = ToolRouter()
    exec_engine = ExecutionEngine(
        router=router,
        safety_engine=safety,
        pending_action_manager=pam,
    )

    req = Request(
        user_input="Submit order form",
        selected_tools=["browser_click"],
    )
    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                tool_name="browser_click",
                description="Click submit order button",
                arguments={"selector": "button#submit-order", "is_submit": True},
            )
        ],
    )

    result = exec_engine.execute(req, plan)

    assert result.success is False
    assert result.requires_confirmation is True
    assert result.pending_action is not None
    assert result.pending_action["tool"] == "browser_click"
    assert result.pending_action["risk_level"] == "sensitive"
    assert "User confirmation is required" in (result.error or "")


def test_execution_engine_resume_and_replay_prevention(monkeypatch: pytest.MonkeyPatch) -> None:
    """ExecutionEngine resumes confirmed browser action, validates safety, verifies, and prevents replay."""
    pam = PendingActionManager()
    safety = SafetyEngine()
    router = ToolRouter()
    verification = VerificationEngine()
    exec_engine = ExecutionEngine(
        router=router,
        safety_engine=safety,
        pending_action_manager=pam,
        verification_engine=verification,
    )

    # Mock tool execution return
    mock_result = {
        "operation": "browser_click",
        "selector": "button#confirm-purchase",
        "url": "https://example.com/receipt",
        "navigation_occurred": True,
        "success": True,
    }
    monkeypatch.setattr(router, "execute_tool", lambda name, message, **kwargs: mock_result)

    # 1. Create pending action
    action = pam.create_pending_action(
        tool_name="browser_click",
        arguments={"selector": "button#confirm-purchase", "is_submit": True},
        risk_level=RiskLevel.SENSITIVE,
        request_id="req_test_123",
        step_number=1,
    )

    # 2. Resume action
    confirm_res = exec_engine.resume_pending_action(action.action_id)

    assert confirm_res.success is True
    assert confirm_res.status == ConfirmationStatus.CONFIRMED
    assert confirm_res.result == mock_result
    assert confirm_res.verification is not None
    assert confirm_res.verification.status == VerificationStatus.VERIFIED

    # 3. Replay prevention: cannot resume already executed action
    replay_res = exec_engine.resume_pending_action(action.action_id)
    assert replay_res.success is False
    assert replay_res.status == ConfirmationStatus.ALREADY_PROCESSED


def test_resume_mandatory_safety_recheck_blocks_tampered_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a pending action's arguments are tampered to target blocked resources, resume rejects it."""
    pam = PendingActionManager()
    safety = SafetyEngine()
    router = ToolRouter()
    exec_engine = ExecutionEngine(
        router=router,
        safety_engine=safety,
        pending_action_manager=pam,
    )

    # Create pending action for browser_navigate
    action = pam.create_pending_action(
        tool_name="browser_navigate",
        arguments={"url": "https://example.com"},
        risk_level=RiskLevel.SENSITIVE,
        request_id="req_nav_test",
        step_number=1,
    )

    # Tamper payload in memory before resume
    action.arguments["url"] = "http://127.0.0.1:8080/evil"

    # Resume must re-run safety check and block it
    confirm_res = exec_engine.resume_pending_action(action.action_id)
    assert confirm_res.success is False
    assert confirm_res.status == ConfirmationStatus.FAILED
    assert (
        "blocked" in (confirm_res.message or "").lower()
        and "security policy" in (confirm_res.message or "").lower()
    )


def test_browser_tools_sync_execute_via_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify tool.execute() works synchronously via browser_runner without event loop collision."""
    from services.browser.runner import browser_runner

    async def _async_mock(val: dict) -> dict:
        return val

    monkeypatch.setattr(
        browser_operations,
        "navigate",
        lambda url, session_id=None: _async_mock(
            {"operation": "browser_navigate", "url": url, "success": True}
        ),
    )
    monkeypatch.setattr(
        browser_operations,
        "read_page",
        lambda session_id=None, max_length=10000: _async_mock(
            {"operation": "browser_read_page", "content": "hello", "success": True}
        ),
    )
    monkeypatch.setattr(
        browser_operations,
        "click",
        lambda selector, session_id=None, is_submit=False: _async_mock(
            {"operation": "browser_click", "selector": selector, "success": True}
        ),
    )
    monkeypatch.setattr(
        browser_operations,
        "type_text",
        lambda selector, text, session_id=None, is_sensitive=False, submit=False: _async_mock(
            {
                "operation": "browser_type",
                "selector": selector,
                "text_length": len(text),
                "success": True,
            }
        ),
    )

    try:
        nav_tool = BrowserNavigateTool()
        nav_res = nav_tool.execute(url="https://example.com")
        assert nav_res["success"] is True
        assert nav_res["operation"] == "browser_navigate"

        read_tool = BrowserReadPageTool()
        read_res = read_tool.execute()
        assert read_res["success"] is True
        assert read_res["operation"] == "browser_read_page"

        click_tool = BrowserClickTool()
        click_res = click_tool.execute(selector="button#ok")
        assert click_res["success"] is True
        assert click_res["operation"] == "browser_click"

        type_tool = BrowserTypeTool()
        type_res = type_tool.execute(selector="input#name", text="ECHO")
        assert type_res["success"] is True
        assert type_res["operation"] == "browser_type"
    finally:
        browser_runner.stop()
