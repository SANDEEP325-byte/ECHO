import pytest

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import PermissionDecision, RiskLevel
from services.brain.execution import ExecutionEngine
from services.security.risk import RiskClassifier
from services.security.safety_engine import SafetyEngine


def test_payload_risk_classification_safe_arguments():
    level = RiskClassifier.classify("calculator", arguments={"expression": "10 + 20"})
    assert level == RiskLevel.SAFE


def test_payload_risk_classification_destructive_format():
    level = RiskClassifier.classify("terminal", arguments={"command": "format C: /fs:NTFS"})
    assert level == RiskLevel.CRITICAL


def test_payload_risk_classification_destructive_rm_rf():
    level = RiskClassifier.classify("terminal", arguments={"command": "rm -rf /"})
    assert level == RiskLevel.CRITICAL


def test_payload_risk_classification_drop_database():
    level = RiskClassifier.classify("database", arguments={"query": "DROP DATABASE production;"})
    assert level == RiskLevel.CRITICAL


def test_payload_risk_classification_sensitive_patterns():
    level_delete = RiskClassifier.classify("file_manager", arguments={"action": "delete", "path": "/data.json"})
    assert level_delete in (RiskLevel.SENSITIVE, RiskLevel.CRITICAL)

    level_chmod = RiskClassifier.classify("terminal", arguments={"command": "chmod 777 run.sh"})
    assert level_chmod in (RiskLevel.SENSITIVE, RiskLevel.CRITICAL)


def test_safety_engine_evaluates_payload_arguments():
    engine = SafetyEngine()

    # Safe operation with safe arguments
    safe_result = engine.evaluate("calculator", arguments={"expression": "2 * 8"})
    assert safe_result.decision == PermissionDecision.ALLOW
    assert safe_result.risk_level == RiskLevel.SAFE

    # Safe operation name but malicious payload argument
    dangerous_result = engine.evaluate("calculator", arguments={"expression": "rm -rf /"})
    assert dangerous_result.decision == PermissionDecision.CONFIRM
    assert dangerous_result.risk_level == RiskLevel.CRITICAL


def test_execution_engine_triggers_confirmation_on_dangerous_payload():
    engine = ExecutionEngine()

    request = Request(user_input="Run calculation")
    request.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Run shell command disguised as calc",
                tool_name="calculator",
                arguments={"expression": "rm -rf /"},
            )
        ],
    )

    result = engine.execute(request, plan)

    assert result.success is False
    assert result.requires_confirmation is True
    assert result.pending_action is not None
    assert result.pending_action["tool"] == "calculator"
    assert result.pending_action["arguments"] == {"expression": "rm -rf /"}
    assert "confirmation is required" in result.error.lower()
