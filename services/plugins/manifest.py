"""Deterministic plugin manifest parser and schema validator for ECHO."""

from __future__ import annotations

import json
import re
from typing import Any

from packages.interfaces.plugin import (
    PluginCapability,
    PluginManifest,
    PluginMetadata,
)
from services.configuration.settings import settings


class ManifestValidationError(Exception):
    """Raised when a plugin manifest is malformed, invalid, or fails security policy."""


class PluginManifestValidator:
    """Strict, deterministic manifest parser and validator.

    All manifests are treated as completely untrusted data.
    """

    MAX_MANIFEST_BYTES: int = 65536  # 64 KB cap to prevent memory exhaustion

    # Reserved IDs that plugins must never use to prevent system impersonation
    RESERVED_IDS: frozenset[str] = frozenset(
        {
            "core",
            "system",
            "echo",
            "brain",
            "builtin",
            "tool",
            "security",
            "admin",
            "internal",
            "plugins",
            "config",
            "memory",
            "voice",
            "desktop",
            "browser",
            "coding",
        }
    )

    # Built-in tool names that plugin tools must never shadow
    BUILTIN_TOOLS: frozenset[str] = frozenset(
        {
            "calculator",
            "time",
            "date",
            "read_file",
            "list_folder",
            "create_folder",
            "copy_file",
            "move_file",
            "delete_file",
            "open_file",
            "open_folder",
            "open_application",
            "execute_command",
            "run_command",
            "open_vscode",
            "open_chrome",
            "run_npm",
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_read_page",
            "browser_download",
            "browser_upload",
            "inspect_code_tree",
            "search_code",
            "read_code",
            "modify_code",
            "apply_patch",
            "run_tests",
        }
    )

    SEMVER_PATTERN: re.Pattern[str] = re.compile(
        r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
        r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
    )

    ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
    TOOL_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")

    REQUIRED_FIELDS: frozenset[str] = frozenset(
        {
            "id",
            "name",
            "version",
            "author",
            "entrypoint",
            "min_echo_version",
            "capabilities",
            "tools",
        }
    )

    @classmethod
    def parse_semver(cls, version_str: str) -> tuple[int, int, int]:
        """Parse a semantic version string into a (major, minor, patch) integer tuple."""
        match = cls.SEMVER_PATTERN.fullmatch(version_str.strip())
        if not match:
            raise ManifestValidationError(
                f"Invalid semantic version '{version_str}'. Must follow MAJOR.MINOR.PATCH format."
            )
        return (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
        )

    @classmethod
    def parse_and_validate(
        cls,
        raw_data: str | bytes | dict[str, Any],
        current_echo_version: str | None = None,
    ) -> PluginManifest:
        """Parse raw manifest content and strictly validate schema, security, and version bounds."""
        # 1. Payload decoding and JSON parsing
        if isinstance(raw_data, (str, bytes)):
            byte_len = len(raw_data.encode("utf-8") if isinstance(raw_data, str) else raw_data)
            if byte_len > cls.MAX_MANIFEST_BYTES:
                raise ManifestValidationError(
                    f"Manifest payload size ({byte_len} bytes) exceeds limit of {cls.MAX_MANIFEST_BYTES} bytes."
                )
            try:
                data = json.loads(raw_data)
            except Exception as exc:
                raise ManifestValidationError(f"Malformed manifest JSON: {exc}") from exc
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            raise ManifestValidationError(
                f"Expected manifest JSON string, bytes, or dict; got {type(raw_data).__name__}."
            )

        if not isinstance(data, dict):
            raise ManifestValidationError("Manifest root must be a JSON object.")

        # 2. Required fields check
        missing = cls.REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise ManifestValidationError(
                f"Manifest is missing required field(s): {', '.join(sorted(missing))}."
            )

        # 3. Plugin ID validation
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ManifestValidationError("Plugin 'id' must be a non-empty string.")
        plugin_id = raw_id.strip()

        if "/" in plugin_id or "\\" in plugin_id or ".." in plugin_id:
            raise ManifestValidationError(
                f"Plugin ID '{plugin_id}' contains illegal path separators or traversal characters."
            )

        if not cls.ID_PATTERN.fullmatch(plugin_id):
            raise ManifestValidationError(
                f"Plugin ID '{plugin_id}' is invalid. Must be lowercase alphanumeric with hyphens or underscores (max 64 chars)."
            )

        if plugin_id in cls.RESERVED_IDS:
            raise ManifestValidationError(
                f"Plugin ID '{plugin_id}' is reserved and cannot be registered."
            )

        # 4. Name, description, author validation
        raw_name = data.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip() or len(raw_name) > 128:
            raise ManifestValidationError(
                "Plugin 'name' must be a non-empty string (max 128 characters)."
            )
        name = raw_name.strip()

        raw_desc = data.get("description", "")
        if not isinstance(raw_desc, str):
            raise ManifestValidationError("Plugin 'description' must be a string.")
        description = raw_desc.strip()

        raw_author = data.get("author")
        if not isinstance(raw_author, str) or not raw_author.strip() or len(raw_author) > 128:
            raise ManifestValidationError(
                "Plugin 'author' must be a non-empty string (max 128 characters)."
            )
        author = raw_author.strip()

        # 5. Entrypoint validation (strictly relative single-file in plugin dir)
        raw_entrypoint = data.get("entrypoint")
        if not isinstance(raw_entrypoint, str) or not raw_entrypoint.strip():
            raise ManifestValidationError("Plugin 'entrypoint' must be a non-empty string.")
        entrypoint = raw_entrypoint.strip()

        if "/" in entrypoint or "\\" in entrypoint or ".." in entrypoint:
            raise ManifestValidationError(
                f"Plugin entrypoint '{entrypoint}' contains illegal path separators or traversal characters. Must be a direct filename."
            )

        if not entrypoint.endswith(".py"):
            raise ManifestValidationError(
                f"Plugin entrypoint '{entrypoint}' must be a Python source file ending with '.py'."
            )

        # 6. Version and Compatibility validation
        raw_version = data.get("version")
        if not isinstance(raw_version, str) or not raw_version.strip():
            raise ManifestValidationError("Plugin 'version' must be a non-empty string.")
        version = raw_version.strip()
        cls.parse_semver(version)

        raw_min_echo = data.get("min_echo_version")
        if not isinstance(raw_min_echo, str) or not raw_min_echo.strip():
            raise ManifestValidationError("Plugin 'min_echo_version' must be a non-empty string.")
        min_echo_version = raw_min_echo.strip()
        min_echo_tuple = cls.parse_semver(min_echo_version)

        max_echo_version: str | None = None
        raw_max_echo = data.get("max_echo_version")
        max_echo_tuple: tuple[int, int, int] | None = None
        if raw_max_echo is not None:
            if not isinstance(raw_max_echo, str) or not raw_max_echo.strip():
                raise ManifestValidationError(
                    "Plugin 'max_echo_version' must be a string if provided."
                )
            max_echo_version = raw_max_echo.strip()
            max_echo_tuple = cls.parse_semver(max_echo_version)

        # Check ECHO core compatibility
        echo_version_str = str(current_echo_version or getattr(settings, "app_version", "0.1.0"))
        echo_version_tuple = cls.parse_semver(echo_version_str)

        if echo_version_tuple < min_echo_tuple:
            raise ManifestValidationError(
                f"Incompatible ECHO version: plugin '{plugin_id}' requires at least ECHO {min_echo_version}, "
                f"but current system version is {echo_version_str}."
            )

        if max_echo_tuple is not None and echo_version_tuple > max_echo_tuple:
            raise ManifestValidationError(
                f"Incompatible ECHO version: plugin '{plugin_id}' requires at most ECHO {max_echo_version}, "
                f"but current system version is {echo_version_str}."
            )

        # 7. Capabilities validation
        raw_capabilities = data.get("capabilities")
        if not isinstance(raw_capabilities, list):
            raise ManifestValidationError("Plugin 'capabilities' must be a list of strings.")

        capabilities_list: list[PluginCapability] = []
        for cap in raw_capabilities:
            if not isinstance(cap, str):
                raise ManifestValidationError(f"Capability item '{cap}' must be a string.")
            try:
                capabilities_list.append(PluginCapability(cap.strip()))
            except ValueError:
                valid_caps = [c.value for c in PluginCapability]
                raise ManifestValidationError(
                    f"Unknown plugin capability '{cap}'. Supported capabilities: {', '.join(valid_caps)}."
                ) from None

        # 8. Tools validation
        raw_tools = data.get("tools")
        if not isinstance(raw_tools, list):
            raise ManifestValidationError("Plugin 'tools' must be a list of tool name strings.")

        tools_list: list[str] = []
        seen_tools: set[str] = set()
        for t in raw_tools:
            if not isinstance(t, str) or not t.strip():
                raise ManifestValidationError(
                    "Each tool name in 'tools' must be a non-empty string."
                )
            t_name = t.strip()

            if "/" in t_name or "\\" in t_name or "." in t_name:
                raise ManifestValidationError(
                    f"Tool name '{t_name}' contains illegal separator characters. Do not include dots or slashes."
                )

            if not cls.TOOL_NAME_PATTERN.fullmatch(t_name):
                raise ManifestValidationError(
                    f"Tool name '{t_name}' is invalid. Must be lowercase alphanumeric with underscores."
                )

            if t_name in seen_tools:
                raise ManifestValidationError(f"Duplicate tool declaration '{t_name}' in manifest.")
            seen_tools.add(t_name)

            # Prevent tool shadowing of built-in ECHO tools
            if t_name in cls.BUILTIN_TOOLS:
                raise ManifestValidationError(
                    f"Tool name '{t_name}' collides with a built-in ECHO system tool."
                )

            tools_list.append(t_name)

        metadata = PluginMetadata(
            id=plugin_id,
            name=name,
            version=version,
            description=description,
            author=author,
            entrypoint=entrypoint,
            min_echo_version=min_echo_version,
            max_echo_version=max_echo_version,
            capabilities=tuple(capabilities_list),
            tools=tuple(tools_list),
        )

        return PluginManifest(metadata=metadata)
