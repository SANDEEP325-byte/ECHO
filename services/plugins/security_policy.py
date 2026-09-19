"""Plugin security policy for argument validation, capability ceiling, and output safety."""

from __future__ import annotations

import json
import re
from typing import Any

from packages.interfaces.plugin import PluginCapability, PluginManifest
from packages.interfaces.security import PermissionDecision, RiskLevel, SafetyResult
from packages.interfaces.tool_schema import ToolDefinition
from services.logging.logger import logger  # type: ignore[attr-defined]


class PluginSecurityPolicy:
    """Enforces strict capability ceilings, argument inspection, and output safety for plugins.

    CRITICAL SECURITY INVARIANTS:
    1. Plugin capability declarations are ceilings/constraints, NEVER permission grants.
    2. A plugin declaring TERMINAL_EXECUTE or NETWORK_ACCESS does NOT bypass SafetyEngine.
    3. All state-changing or sensitive operations mandate PermissionDecision.CONFIRM.
    4. Malformed or ambiguous arguments fail closed.
    5. Output is bounded to 64KB and treated as untrusted data.
    6. Sanitization mitigates prompt injection risks, but does NOT guarantee 100% prevention
       of semantic indirect prompt injection.
    """

    MAX_PLUGIN_OUTPUT_BYTES = 65536  # 64KB strict bound

    SENSITIVE_ARG_KEYS = frozenset(
        {
            "password",
            "token",
            "secret",
            "key",
            "auth",
            "api_key",
            "credentials",
            "pass",
            "pwd",
            "access_token",
            "private_key",
        }
    )

    SENSITIVE_FILE_PATTERNS = (
        ".env",
        ".secrets",
        "id_rsa",
        "id_ed25519",
        "credentials",
        ".aws",
        ".ssh",
        ".key",
        ".pem",
        "shadow",
        "passwd",
        "authorized_keys",
    )

    DANGEROUS_COMMAND_PATTERNS = (
        "rm -rf",
        "rmdir /s",
        "del /s",
        "format ",
        "drop table",
        "drop database",
        "truncate ",
        ":(){ :|:& };:",
        "shutdown",
        "reboot",
        "mkfs",
        "dd if=",
    )

    COMMAND_CHAINING_PATTERNS = (";", "&&", "||", "|", "`", "$(", ">", "<")

    CLOUD_METADATA_HOSTS = (
        "169.254.169.254",
        "metadata.google.internal",
        "instance-data",
    )

    PROMPT_INJECTION_MARKERS = (
        ("SYSTEM:", "[DEFUSED_DIRECTIVE_SYSTEM]"),
        ("DEVELOPER:", "[DEFUSED_DIRECTIVE_DEVELOPER]"),
        ("<|im_start|>", "[DEFUSED_TAG_IM_START]"),
        ("<|im_end|>", "[DEFUSED_TAG_IM_END]"),
        ("[INST]", "[DEFUSED_TAG_INST]"),
        ("[/INST]", "[DEFUSED_TAG_CLOSE_INST]"),
        ("<<SYS>>", "[DEFUSED_TAG_SYS]"),
        ("<</SYS>>", "[DEFUSED_TAG_CLOSE_SYS]"),
        ("Ignore previous instructions", "[DEFUSED_DIRECTIVE_IGNORE_PREVIOUS]"),
        ("ignore all previous instructions", "[DEFUSED_DIRECTIVE_IGNORE_ALL_PREVIOUS]"),
    )

    @classmethod
    def evaluate_plugin_call(
        cls,
        manifest: PluginManifest,
        tool_definition: ToolDefinition | None,
        arguments: dict[str, Any] | None,
        operation_name: str,
    ) -> SafetyResult:
        """Evaluate a plugin tool call against capability ceilings and argument safety.

        Fail-closed: Returns SafetyResult with ALLOW, CONFIRM, or BLOCK.
        """
        args = arguments or {}
        declared_caps = set(manifest.capabilities)

        # 1. Schema parameter validation (if tool definition is available)
        if tool_definition is not None and tool_definition.parameters:
            schema_err = cls._validate_schema(tool_definition, args)
            if schema_err:
                logger.warning(
                    "Plugin '{}' tool '{}' failed schema validation: {}",
                    manifest.id,
                    operation_name,
                    schema_err,
                )
                return SafetyResult(
                    operation=operation_name,
                    risk_level=RiskLevel.CRITICAL,
                    decision=PermissionDecision.BLOCK,
                    reason=f"Argument schema validation failed: {schema_err}",
                )

        # 2. Inspect arguments for hard security violations (traversal, UNC, null bytes, cloud metadata)
        hard_violation = cls._inspect_hard_violations(args)
        if hard_violation:
            logger.warning(
                "Hard security violation detected for plugin '{}' tool '{}': {}",
                manifest.id,
                operation_name,
                hard_violation,
            )
            return SafetyResult(
                operation=operation_name,
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.BLOCK,
                reason=hard_violation,
            )

        # 3. Capability ceiling check (Does the operation/arguments require capabilities not declared?)
        ceiling_err = cls._check_capability_ceilings(declared_caps, operation_name, args)
        if ceiling_err:
            logger.warning(
                "Plugin '{}' exceeded capability ceiling for tool '{}': {}",
                manifest.id,
                operation_name,
                ceiling_err,
            )
            return SafetyResult(
                operation=operation_name,
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.BLOCK,
                reason=ceiling_err,
            )

        # 4. Check for dangerous command / payload patterns that escalate risk to CRITICAL (CONFIRM required)
        dangerous_pattern = cls._inspect_dangerous_patterns(args)
        if dangerous_pattern:
            return SafetyResult(
                operation=operation_name,
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.CONFIRM,
                reason=f"Dangerous payload pattern detected: {dangerous_pattern}",
            )

        # 5. Determine risk level and permission decision
        # Remember: Capability declaration is NOT a grant! State-modifying operations require CONFIRM.
        if cls._is_state_modifying(declared_caps, operation_name, args):
            return SafetyResult(
                operation=operation_name,
                risk_level=RiskLevel.SENSITIVE,
                decision=PermissionDecision.CONFIRM,
                reason=f"Plugin '{manifest.id}' operation '{operation_name}' is state-modifying and requires confirmation.",
            )

        # If it is strictly read-only and no state-changing capability is required:
        if (
            PluginCapability.FILESYSTEM_READ in declared_caps
            or PluginCapability.SYSTEM_INFO in declared_caps
        ) and not (
            PluginCapability.FILESYSTEM_WRITE in declared_caps
            or PluginCapability.TERMINAL_EXECUTE in declared_caps
            or PluginCapability.NETWORK_ACCESS in declared_caps
        ):
            return SafetyResult(
                operation=operation_name,
                risk_level=RiskLevel.SAFE,
                decision=PermissionDecision.ALLOW,
                reason="Read-only plugin operation.",
            )

        # Default fail-closed to SENSITIVE / CONFIRM for all other plugin operations
        return SafetyResult(
            operation=operation_name,
            risk_level=RiskLevel.SENSITIVE,
            decision=PermissionDecision.CONFIRM,
            reason=f"Plugin operation '{operation_name}' requires confirmation.",
        )

    @classmethod
    def _validate_schema(cls, tool_def: ToolDefinition, args: dict[str, Any]) -> str | None:
        """Validate arguments against tool definition parameter types and requirements."""
        param_map = {p.name: p for p in tool_def.parameters}

        # Check required parameters
        for p in tool_def.parameters:
            if p.required and p.name not in args:
                return f"Missing required parameter '{p.name}'"

        # Check types
        type_mapping: dict[str, type | tuple[type, ...]] = {
            "str": str,
            "string": str,
            "int": int,
            "integer": int,
            "float": (float, int),
            "number": (float, int),
            "bool": bool,
            "boolean": bool,
            "list": list,
            "dict": dict,
        }

        for arg_name, arg_val in args.items():
            param = param_map.get(arg_name)
            if param is None:
                # Disallow unexpected extra arguments
                return f"Unexpected argument '{arg_name}' not defined in tool schema"

            expected_type_name = str(param.type).lower().strip()
            expected_type = type_mapping.get(expected_type_name)
            if expected_type is not None and not isinstance(arg_val, expected_type):
                return (
                    f"Parameter '{arg_name}' must be of type '{param.type}', "
                    f"got '{type(arg_val).__name__}'"
                )

        return None

    @classmethod
    def _inspect_hard_violations(cls, args: dict[str, Any]) -> str | None:
        """Inspect argument values for hard security violations (traversal, UNC, metadata, chaining)."""
        for key, val in args.items():
            str_val = str(val) if val is not None else ""

            # Check null bytes
            if "\0" in str_val:
                return f"Null byte detected in argument '{key}'"

            # Check path traversal and sensitive files
            if key in (
                "path",
                "file",
                "filepath",
                "destination",
                "source",
                "filename",
                "dir",
                "target_path",
            ):
                if ".." in str_val:
                    return f"Path traversal ('..') detected in argument '{key}'"
                if str_val.startswith((r"\\", "//")):
                    return f"UNC network path detected in argument '{key}'"
                for sensitive in cls.SENSITIVE_FILE_PATTERNS:
                    if sensitive in str_val.lower():
                        return (
                            f"Access to sensitive target '{sensitive}' blocked in argument '{key}'"
                        )
                lower_val = str_val.lower()
                if (
                    lower_val.startswith(("c:\\windows", "/etc", "/bin", "/usr"))
                    or "system32" in lower_val
                ):
                    return f"Access to protected system location blocked in argument '{key}'"

            # Check command chaining
            if key in ("command", "cmd", "script", "shell", "exec"):
                for chaining in cls.COMMAND_CHAINING_PATTERNS:
                    if chaining in str_val:
                        return f"Command chaining / redirection ('{chaining}') detected in argument '{key}'"

            # Check network / URL targets
            if key in ("url", "endpoint", "host", "uri"):
                lower_url = str_val.lower()
                if not lower_url.startswith(("http://", "https://")):
                    return f"Invalid URL scheme in argument '{key}': only http/https allowed"
                for meta_host in cls.CLOUD_METADATA_HOSTS:
                    if meta_host in lower_url:
                        return f"Access to cloud metadata host '{meta_host}' blocked in argument '{key}'"

        return None

    @classmethod
    def _inspect_dangerous_patterns(cls, args: dict[str, Any]) -> str | None:
        """Inspect argument values for dangerous system command or destructive patterns."""
        for key, val in args.items():
            str_val = str(val).lower() if val is not None else ""
            for dangerous in cls.DANGEROUS_COMMAND_PATTERNS:
                if dangerous in str_val:
                    return f"Destructive command pattern '{dangerous}' detected in argument '{key}'"
        return None

    @classmethod
    def _check_capability_ceilings(
        cls,
        declared_caps: set[PluginCapability],
        operation_name: str,
        args: dict[str, Any],
    ) -> str | None:
        """Ensure the tool does not perform operations beyond its declared capabilities."""
        # Check command execution
        has_command_args = any(k in args for k in ("command", "cmd", "script", "shell", "exec"))
        if has_command_args and PluginCapability.TERMINAL_EXECUTE not in declared_caps:
            return "Operation attempted terminal command execution without declared 'terminal_execute' capability"

        # Check network access
        has_url_args = any(k in args for k in ("url", "endpoint", "host", "uri"))
        if has_url_args and (
            PluginCapability.NETWORK_ACCESS not in declared_caps
            and PluginCapability.BROWSER_ACCESS not in declared_caps
        ):
            return "Operation attempted network/URL access without declared 'network_access' or 'browser_access' capability"

        # Check filesystem operations
        has_path_args = any(
            k in args
            for k in (
                "path",
                "file",
                "filepath",
                "destination",
                "source",
                "filename",
                "dir",
                "target_path",
            )
        )
        if has_path_args:
            is_write_intent = any(
                w in operation_name.lower()
                for w in ("write", "create", "delete", "remove", "modify", "save", "patch")
            )
            if is_write_intent and PluginCapability.FILESYSTEM_WRITE not in declared_caps:
                return "Operation attempted filesystem write without declared 'filesystem_write' capability"
            if not is_write_intent and (
                PluginCapability.FILESYSTEM_READ not in declared_caps
                and PluginCapability.FILESYSTEM_WRITE not in declared_caps
            ):
                return "Operation attempted filesystem access without declared 'filesystem_read' or 'filesystem_write' capability"

        return None

    @classmethod
    def _is_state_modifying(
        cls,
        declared_caps: set[PluginCapability],
        operation_name: str,
        args: dict[str, Any],
    ) -> bool:
        """Determine if a plugin operation modifies external state."""
        state_modifying_caps = {
            PluginCapability.FILESYSTEM_WRITE,
            PluginCapability.TERMINAL_EXECUTE,
            PluginCapability.AUTOMATION,
        }
        if bool(declared_caps & state_modifying_caps):
            return True

        # State modifying keywords in operation name
        state_keywords = (
            "write",
            "create",
            "delete",
            "remove",
            "modify",
            "exec",
            "run",
            "patch",
            "send",
            "post",
        )
        return any(kw in operation_name.lower() for kw in state_keywords)

    @classmethod
    def redact_arguments(cls, args: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive parameter values (passwords, tokens, keys) for safe confirmation display."""
        safe_args: dict[str, Any] = {}
        for k, v in args.items():
            if any(sensitive in k.lower() for sensitive in cls.SENSITIVE_ARG_KEYS):
                safe_args[k] = "[REDACTED]"
            elif isinstance(v, dict):
                safe_args[k] = cls.redact_arguments(v)
            else:
                safe_args[k] = v
        return safe_args

    @classmethod
    def sanitize_and_bound_output(cls, raw_output: Any, plugin_id: str) -> Any:
        """Bound output size to 64KB, defuse prompt injection tokens, and redact secrets.

        NOTE: Sanitization mitigates prompt injection risks, but does NOT guarantee 100%
        prevention of semantic indirect prompt injection. Downstream components must treat
        all plugin output as untrusted data.
        """
        if raw_output is None:
            return None

        # Handle string output
        if isinstance(raw_output, str):
            sanitized = cls._sanitize_string(raw_output)
            if len(sanitized.encode("utf-8")) > cls.MAX_PLUGIN_OUTPUT_BYTES:
                # Truncate at 64KB
                truncated = sanitized.encode("utf-8")[: cls.MAX_PLUGIN_OUTPUT_BYTES].decode(
                    "utf-8", errors="ignore"
                )
                return f"{truncated}\n[TRUNCATED: Plugin '{plugin_id}' output exceeded 64KB limit]"
            return sanitized

        # Handle dict or list output
        if isinstance(raw_output, (dict, list)):
            try:
                serialized = json.dumps(raw_output, default=str)
                if len(serialized.encode("utf-8")) > cls.MAX_PLUGIN_OUTPUT_BYTES:
                    truncated = serialized.encode("utf-8")[: cls.MAX_PLUGIN_OUTPUT_BYTES].decode(
                        "utf-8", errors="ignore"
                    )
                    return (
                        f"{truncated}\n[TRUNCATED: Plugin '{plugin_id}' output exceeded 64KB limit]"
                    )
                # Sanitize dictionary values recursively
                return cls._sanitize_data_structure(raw_output)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error serializing plugin output for bounding: {}", exc)
                return str(raw_output)[: cls.MAX_PLUGIN_OUTPUT_BYTES]

        # Primitive types (int, float, bool)
        return raw_output

    @classmethod
    def _sanitize_string(cls, text: str) -> str:
        """Defuse instruction-like prompt injection markers and redact secret patterns."""
        result = text
        # Defuse instruction markers
        for marker, replacement in cls.PROMPT_INJECTION_MARKERS:
            result = result.replace(marker, replacement)

        # Redact common secret patterns (e.g. Bearer tokens, GitHub tokens)
        result = re.sub(
            r"Bearer\s+[A-Za-z0-9_\-\.]{12,}",
            "Bearer [REDACTED_TOKEN]",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(r"ghp_[A-Za-z0-9]{20,}", "ghp_[REDACTED_TOKEN]", result)
        result = re.sub(r"AKIA[0-9A-Z]{16}", "AKIA[REDACTED_AWS_KEY]", result)

        return result

    @classmethod
    def _sanitize_data_structure(cls, data: Any) -> Any:
        """Recursively sanitize strings inside data structures."""
        if isinstance(data, dict):
            return {k: cls._sanitize_data_structure(v) for k, v in data.items()}
        if isinstance(data, list):
            return [cls._sanitize_data_structure(item) for item in data]
        if isinstance(data, str):
            return cls._sanitize_string(data)
        return data
