from typing import Any

from packages.interfaces.security import (
    PermissionDecision,
    RiskLevel,
    SafetyResult,
)
from services.security.permission_manager import permission_manager
from services.security.risk import risk_classifier
from services.logging.logger import logger

class SafetyEngine:
    """Evaluates whether an ECHO operation is safe to execute."""
    
    def evaluate(
        self,
        operation: str,
        arguments: dict[str, Any] | None = None,
    ) -> SafetyResult:
        """Evaluate an operation and return its safety decision."""
        
        normalized = operation.strip().lower()
        
        logger.info(
            "Evaluating safety for operation: {} (has_args={})",
            normalized,
            arguments is not None,
        )
        
        risk_level = risk_classifier.classify(normalized, arguments=arguments)
        
        decision = permission_manager.decide(risk_level)

        # Specialized policy check for browser navigation targets
        if normalized == "browser_navigate" and arguments and "url" in arguments:
            from services.browser.policy import browser_security_policy

            url_check = browser_security_policy.validate_url(str(arguments["url"]))
            if not url_check.allowed:
                if url_check.decision == PermissionDecision.CONFIRM:
                    decision = PermissionDecision.CONFIRM
                    risk_level = RiskLevel.SENSITIVE
                    reason = url_check.reason
                else:
                    decision = PermissionDecision.BLOCK
                    risk_level = RiskLevel.CRITICAL
                    reason = url_check.reason
            else:
                decision = PermissionDecision.ALLOW
                risk_level = RiskLevel.SAFE
                reason = url_check.reason
        elif decision == PermissionDecision.ALLOW:
            reason = "Operation is allowed."
            
        elif decision == PermissionDecision.CONFIRM:
            reason = "User confirmation is required before execution."
            
        else:
            reason = "Operation is blocked by the security policy."
            
        result = SafetyResult(
            decision=decision,
            risk_level=risk_level,
            reason=reason,
            operation=normalized,
            metadata=arguments,
        )
        
        logger.info(
            "Safety evaluation completed: operation={}, risk={}, decision={}",
            normalized,
            risk_level.value,
            decision.value,
        )
        
        return result
    
safety_engine = SafetyEngine()