from packages.interfaces.security import (
    PermissionDecision,
    RiskLevel,
    SafetyResult,
)
from services.security.risk import RiskClassifier
from services.security.permission_manager import PermissionManager
from services.security.safety_engine import SafetyEngine

def test_risk_levels_exist():
    assert RiskLevel.SAFE.value == "safe"
    assert RiskLevel.MODERATE.value == "moderate"
    assert RiskLevel.SENSITIVE.value == "sensitive"
    assert RiskLevel.CRITICAL.value == "critical"
    
def test_permission_decisions_exist():
    assert PermissionDecision.ALLOW.value == "allow"
    assert PermissionDecision.CONFIRM.value == "confirm"
    assert PermissionDecision.BLOCK.value == "block"
    
def test_safety_result_stores_security_decision():
    result = SafetyResult(
        decision=PermissionDecision.ALLOW,
        risk_level=RiskLevel.SAFE,
        reason="Operation is considered safe.",
        operation="calculator",
    )
    
    assert result.decision == PermissionDecision.ALLOW
    assert result.risk_level == RiskLevel.SAFE
    assert result.reason == "Operation is considered safe."
    assert result.operation == "calculator"
    
def test_safety_result_supports_metadata():
    result = SafetyResult(
        decision=PermissionDecision.CONFIRM,
        risk_level=RiskLevel.SENSITIVE,
        reason="User confirmation is required.",
        operation="delete_file",
        metadata={"path": "example.txt"},
    )
    
    assert result.metadata == {"path": "example.txt"}
    
def test_safety_result_is_immutable():
    result = SafetyResult(
        decision=PermissionDecision.ALLOW,
        risk_level=RiskLevel.SAFE,
        reason="Safe operation.",
        operation="calculator",
    )
    
    try:
        result.operation = "terminal"
        assert False
    except AttributeError:
        pass
    
def test_calculator_is_safe():
    assert (
        RiskClassifier.classify("calculator")
        == RiskLevel.SAFE
    )

def test_read_file_is_safe():
    assert (
        RiskClassifier.classify("read_file")
        == RiskLevel.SAFE
    )

def test_open_chrome_is_moderate():
    assert (
        RiskClassifier.classify("open_chrome")
        == RiskLevel.MODERATE
    )

def test_run_npm_is_moderate():
    assert (
        RiskClassifier.classify("run_npm")
        == RiskLevel.MODERATE
    )

def test_delete_file_is_sensitive():
    assert (
        RiskClassifier.classify("delete_file")
        == RiskLevel.SENSITIVE
    )

def test_git_push_is_sensitive():
    assert (
        RiskClassifier.classify("git_push")
        == RiskLevel.SENSITIVE
    )

def test_format_drive_is_critical():
    assert (
        RiskClassifier.classify("format_drive")
        == RiskLevel.CRITICAL
    )

def test_massive_delete_is_critical():
    assert (
        RiskClassifier.classify("massive_delete")
        == RiskLevel.CRITICAL
    )

def test_unknown_operation_is_not_safe():
    assert (
        RiskClassifier.classify("unknown_operation")
        == RiskLevel.SENSITIVE
    )

def test_operation_matching_is_case_insensitive():
    assert (
        RiskClassifier.classify("  CALCULATOR  ")
        == RiskLevel.SAFE
    )
    
def test_safe_operation_is_allowed():
    assert (
        PermissionManager.decide(RiskLevel.SAFE)
        == PermissionDecision.ALLOW
    )
    
def test_moderate_operation_is_allowed():
    assert (
        PermissionManager.decide(RiskLevel.MODERATE)
        == PermissionDecision.ALLOW
    )
    
def test_sensitive_operation_requires_confirmation():
    assert (
        PermissionManager.decide(RiskLevel.SENSITIVE)
        == PermissionDecision.CONFIRM
    )
    
def test_critical_operation_requires_confirmation():
    assert (
        PermissionManager.decide(RiskLevel.CRITICAL)
        == PermissionDecision.CONFIRM
    )
    
def test_safety_engine_allows_safe_operation():
    result = SafetyEngine().evaluate("calculator")
    
    assert result.decision == PermissionDecision.ALLOW
    assert result.risk_level == RiskLevel.SAFE
    assert result.operation == "calculator"
    
def test_saafety_engine_allows_moderate_operation():
    result = SafetyEngine().evaluate("open_chrome")
    
    assert result.decision == PermissionDecision.ALLOW
    assert result.risk_level == RiskLevel.MODERATE
    
def test_safety_engine_requires_confirmation_for_sensitive_operation():
    result = SafetyEngine().evaluate("delete_file")

    assert result.decision == PermissionDecision.CONFIRM
    assert result.risk_level == RiskLevel.SENSITIVE


def test_safety_engine_requires_confirmation_for_critical_operation():
    result = SafetyEngine().evaluate("format_drive")

    assert result.decision == PermissionDecision.CONFIRM
    assert result.risk_level == RiskLevel.CRITICAL


def test_safety_engine_normalizes_operation():
    result = SafetyEngine().evaluate("  CALCULATOR  ")

    assert result.operation == "calculator"
    assert result.risk_level == RiskLevel.SAFE


def test_safety_engine_provides_reason():
    result = SafetyEngine().evaluate("delete_file")

    assert result.reason
    assert "confirmation" in result.reason.lower()