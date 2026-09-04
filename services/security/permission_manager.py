from packages.interfaces.security import (
    PermissionDecision,
    RiskLevel,
)


class PermissionManager:
    """Determines the permission decision for a given risk level."""
    
    @staticmethod
    def decide(risk_level: RiskLevel) -> PermissionDecision:
        """Return the required permission decision for a risk level."""
        
        if risk_level == RiskLevel.SAFE:
            return PermissionDecision.ALLOW
        
        if risk_level == RiskLevel.MODERATE:
            return PermissionDecision.ALLOW
        
        if risk_level == RiskLevel.SENSITIVE:
            return PermissionDecision.CONFIRM
        
        if risk_level == RiskLevel.CRITICAL:
            return PermissionDecision.CONFIRM
        
        # Unknown risk levels must never be allowed.
        return PermissionDecision.BLOCK
    
permission_manager = PermissionManager()