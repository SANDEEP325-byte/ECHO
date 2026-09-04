from dataclasses import dataclass
from enum import Enum
from typing import Any

class RiskLevel(str, Enum):
    """Defines the risk level of an ECHO operation."""
    
    SAFE = "safe"
    MODERATE = "moderate"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"
    
class PermissionDecision(str, Enum):
    """Defines the permission decision for an operation."""
    
    ALLOW = "allow"
    CONFIRM = "confirm"
    BLOCK = "block"
    
@dataclass(frozen=True)
class SafetyResult:
    """Represents the result of a security/safety evaluation."""
    
    decision: PermissionDecision
    risk_level: RiskLevel
    reason: str
    operation: str
    metadata: dict[str, Any] | None = None