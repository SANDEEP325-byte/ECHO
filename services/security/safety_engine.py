from typing import Any

from packages.interfaces.security import (
    PermissionDecision,
    RiskLevel,
    SafetyResult,
)
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.security.permission_manager import permission_manager
from services.security.risk import risk_classifier


class SafetyEngine:
    """Evaluates whether an ECHO operation is safe to execute."""

    def __init__(
        self,
        browser_policy: Any | None = None,
        desktop_policy: Any | None = None,
        plugin_manager: Any | None = None,
    ) -> None:
        self.browser_policy = browser_policy
        self.desktop_policy = desktop_policy
        self.plugin_manager = plugin_manager

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

        # Specialized policy check for plugin tools
        if "." in normalized:
            from packages.common.tool_registry import tool_registry
            from services.plugins import plugin_manager as default_plugin_manager
            from services.plugins.security_policy import PluginSecurityPolicy

            plugin_id, _ = normalized.split(".", 1)
            p_mgr = self.plugin_manager or default_plugin_manager
            plugin_record = p_mgr.get_plugin(plugin_id)

            if plugin_record is not None:
                if not p_mgr.is_plugin_active(plugin_id):
                    return SafetyResult(
                        operation=normalized,
                        risk_level=RiskLevel.CRITICAL,
                        decision=PermissionDecision.BLOCK,
                        reason=f"Plugin '{plugin_id}' is not active or has been disabled.",
                    )

                tool = tool_registry.get(normalized)
                tool_def = getattr(tool, "definition", None) if tool else None

                return PluginSecurityPolicy.evaluate_plugin_call(
                    manifest=plugin_record.manifest,
                    tool_definition=tool_def,
                    arguments=arguments,
                    operation_name=normalized,
                )

        risk_level = risk_classifier.classify(normalized, arguments=arguments)

        decision = permission_manager.decide(risk_level)

        # Specialized policy check for browser navigation targets
        if normalized == "browser_navigate" and arguments and "url" in arguments:
            from services.browser.policy import browser_security_policy

            b_policy = self.browser_policy or browser_security_policy
            url_check = b_policy.validate_url(str(arguments["url"]))
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

        elif normalized == "browser_download":
            from pathlib import Path

            from services.browser.operations import BrowserOperations
            from services.browser.policy import browser_security_policy
            from services.desktop.policy import OperationType, desktop_security_policy

            b_policy = self.browser_policy or browser_security_policy
            d_policy = self.desktop_policy or desktop_security_policy

            # If URL is provided, validate URL safety
            if arguments and "url" in arguments and arguments["url"]:
                url_check = b_policy.validate_url(str(arguments["url"]))
                if not url_check.allowed:
                    decision = PermissionDecision.BLOCK
                    risk_level = RiskLevel.CRITICAL
                    reason = f"Download URL violates security policy: {url_check.reason}"
                else:
                    decision = PermissionDecision.CONFIRM
                    risk_level = RiskLevel.SENSITIVE
                    reason = (
                        "User confirmation is required before downloading files from the browser."
                    )
            else:
                decision = PermissionDecision.CONFIRM
                risk_level = RiskLevel.SENSITIVE
                reason = "User confirmation is required before downloading files from the browser."

            # If destination_path is provided, validate through DesktopSecurityPolicy
            if (
                decision != PermissionDecision.BLOCK
                and arguments
                and "destination_path" in arguments
                and arguments["destination_path"]
            ):
                dest_str = str(arguments["destination_path"])
                dest_check = d_policy.validate(dest_str, OperationType.CREATE)
                if not dest_check.allowed:
                    decision = PermissionDecision.BLOCK
                    risk_level = RiskLevel.CRITICAL
                    reason = f"Download destination violates security policy: {dest_check.reason}"
                else:
                    ext = Path(dest_str).suffix.lower()
                    if ext in BrowserOperations.BLOCKED_DOWNLOAD_EXTENSIONS:
                        decision = PermissionDecision.BLOCK
                        risk_level = RiskLevel.CRITICAL
                        reason = (
                            f"Download of executable file with extension '{ext}' is prohibited."
                        )

        elif normalized == "browser_upload":
            from services.desktop.policy import OperationType, desktop_security_policy

            d_policy = self.desktop_policy or desktop_security_policy

            if arguments and "file_path" in arguments and arguments["file_path"]:
                src_str = str(arguments["file_path"])
                src_check = d_policy.validate(src_str, OperationType.READ)
                if not src_check.allowed:
                    decision = PermissionDecision.BLOCK
                    risk_level = RiskLevel.CRITICAL
                    reason = f"Upload source path violates security policy: {src_check.reason}"
                else:
                    decision = PermissionDecision.CONFIRM
                    risk_level = RiskLevel.SENSITIVE
                    reason = (
                        "User confirmation is required before uploading local files to the browser."
                    )
            else:
                decision = PermissionDecision.CONFIRM
                risk_level = RiskLevel.SENSITIVE
                reason = (
                    "User confirmation is required before uploading local files to the browser."
                )

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
