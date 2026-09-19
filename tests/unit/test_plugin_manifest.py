"""Unit tests for ECHO Plugin Manifest parsing and schema validation (Phase 8A)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from packages.interfaces.plugin import PluginCapability, PluginManifest
from services.plugins.manifest import ManifestValidationError, PluginManifestValidator


@pytest.fixture
def valid_manifest_dict() -> dict[str, Any]:
    """Return a baseline valid manifest dictionary."""
    return {
        "id": "git_tools",
        "name": "Git Integration",
        "version": "1.0.0",
        "description": "Git repository inspection tools for ECHO",
        "author": "ECHO Team",
        "entrypoint": "main.py",
        "min_echo_version": "0.1.0",
        "capabilities": ["filesystem_read", "terminal_execute"],
        "tools": ["status", "diff_summary"],
    }


# ---------------------------------------------------------------------------
# 1. Valid Manifest Parsing
# ---------------------------------------------------------------------------


def test_parse_valid_manifest(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify standard valid manifest parses successfully into PluginManifest."""
    manifest = PluginManifestValidator.parse_and_validate(
        valid_manifest_dict, current_echo_version="0.1.0"
    )
    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "git_tools"
    assert manifest.name == "Git Integration"
    assert manifest.version == "1.0.0"
    assert manifest.entrypoint == "main.py"
    assert PluginCapability.FILESYSTEM_READ in manifest.capabilities
    assert PluginCapability.TERMINAL_EXECUTE in manifest.capabilities
    assert manifest.tools == ("status", "diff_summary")

    # Verify dictionary serialization
    serialized = manifest.to_dict()
    assert serialized["id"] == "git_tools"
    assert "filesystem_read" in serialized["capabilities"]


def test_parse_valid_manifest_json_string(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify parsing from JSON string and bytes representations."""
    json_str = json.dumps(valid_manifest_dict)
    manifest = PluginManifestValidator.parse_and_validate(json_str, current_echo_version="0.1.0")
    assert manifest.id == "git_tools"

    json_bytes = json_str.encode("utf-8")
    manifest_bytes = PluginManifestValidator.parse_and_validate(
        json_bytes, current_echo_version="0.1.0"
    )
    assert manifest_bytes.id == "git_tools"


# ---------------------------------------------------------------------------
# 2. Malformed JSON & Payload Limits
# ---------------------------------------------------------------------------


def test_reject_malformed_json() -> None:
    """Verify unparseable JSON fails closed with ManifestValidationError."""
    with pytest.raises(ManifestValidationError, match="Malformed manifest JSON"):
        PluginManifestValidator.parse_and_validate("{not valid json: true}")


def test_reject_non_dict_root() -> None:
    """Verify arrays or primitives at manifest root fail closed."""
    with pytest.raises(ManifestValidationError, match="Manifest root must be a JSON object"):
        PluginManifestValidator.parse_and_validate('["plugin_array"]')

    with pytest.raises(ManifestValidationError, match="Manifest root must be a JSON object"):
        PluginManifestValidator.parse_and_validate('"just a string"')


def test_reject_oversized_manifest() -> None:
    """Verify manifests exceeding 64KB fail closed to prevent memory exhaustion."""
    large_payload = " " * 70000
    with pytest.raises(ManifestValidationError, match="payload size .* exceeds limit"):
        PluginManifestValidator.parse_and_validate(large_payload)


# ---------------------------------------------------------------------------
# 3. Missing Required Fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "name",
        "version",
        "author",
        "entrypoint",
        "min_echo_version",
        "capabilities",
        "tools",
    ],
)
def test_reject_missing_required_field(valid_manifest_dict: dict[str, Any], field: str) -> None:
    """Verify missing any required field fails closed."""
    del valid_manifest_dict[field]
    with pytest.raises(ManifestValidationError, match=f"missing required field.*{field}"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


# ---------------------------------------------------------------------------
# 4. Plugin ID Validation & Reserved Names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "GitTools",  # Uppercase
        "git tools",  # Spaces
        "git@tools",  # Special characters
        "-git",  # Starts with hyphen
        "_git",  # Starts with underscore
        "",  # Empty
    ],
)
def test_reject_invalid_plugin_id_format(valid_manifest_dict: dict[str, Any], bad_id: str) -> None:
    """Verify invalid ID formats fail closed."""
    valid_manifest_dict["id"] = bad_id
    with pytest.raises(
        ManifestValidationError, match="Plugin ID.*is invalid|must be a non-empty string"
    ):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


@pytest.mark.parametrize(
    "traversal_id",
    [
        "../escape",
        "..\\escape",
        "dir/plugin",
        "dir\\plugin",
    ],
)
def test_reject_path_traversal_in_id(
    valid_manifest_dict: dict[str, Any], traversal_id: str
) -> None:
    """Verify path traversal or directory separators in ID fail closed."""
    valid_manifest_dict["id"] = traversal_id
    with pytest.raises(ManifestValidationError, match="illegal path separators or traversal"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


@pytest.mark.parametrize(
    "reserved",
    [
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
    ],
)
def test_reject_reserved_plugin_ids(valid_manifest_dict: dict[str, Any], reserved: str) -> None:
    """Verify reserved system IDs cannot be claimed by plugins."""
    valid_manifest_dict["id"] = reserved
    with pytest.raises(ManifestValidationError, match="is reserved and cannot be registered"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


# ---------------------------------------------------------------------------
# 5. Entrypoint Path Safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_entrypoint",
    [
        "../escape.py",
        "subdir/main.py",
        "subdir\\main.py",
        "..\\root.py",
    ],
)
def test_reject_traversal_in_entrypoint(
    valid_manifest_dict: dict[str, Any], bad_entrypoint: str
) -> None:
    """Verify entrypoints attempting path traversal are rejected."""
    valid_manifest_dict["entrypoint"] = bad_entrypoint
    with pytest.raises(ManifestValidationError, match="illegal path separators or traversal"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


def test_reject_non_python_entrypoint(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify entrypoint must end with .py."""
    valid_manifest_dict["entrypoint"] = "main.sh"
    with pytest.raises(
        ManifestValidationError, match="must be a Python source file ending with '.py'"
    ):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


# ---------------------------------------------------------------------------
# 6. Versioning & Core Compatibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_version",
    [
        "1.0",
        "v1.0.0",
        "beta-1",
        "1.0.0.0",
    ],
)
def test_reject_invalid_semver_format(
    valid_manifest_dict: dict[str, Any], bad_version: str
) -> None:
    """Verify non-standard semver strings are rejected."""
    valid_manifest_dict["version"] = bad_version
    with pytest.raises(ManifestValidationError, match="Invalid semantic version"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


def test_reject_incompatible_higher_min_echo_version(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify plugin requiring higher ECHO version than current fails closed."""
    valid_manifest_dict["min_echo_version"] = "2.0.0"
    with pytest.raises(
        ManifestValidationError, match="Incompatible ECHO version.*requires at least"
    ):
        PluginManifestValidator.parse_and_validate(
            valid_manifest_dict, current_echo_version="0.1.0"
        )


def test_reject_incompatible_lower_max_echo_version(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify plugin with expired max_echo_version fails closed."""
    valid_manifest_dict["min_echo_version"] = "0.0.1"
    valid_manifest_dict["max_echo_version"] = "0.0.9"
    with pytest.raises(
        ManifestValidationError, match="Incompatible ECHO version.*requires at most"
    ):
        PluginManifestValidator.parse_and_validate(
            valid_manifest_dict, current_echo_version="0.1.0"
        )


# ---------------------------------------------------------------------------
# 7. Capabilities & Permissions Validation
# ---------------------------------------------------------------------------


def test_reject_unknown_capability(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify undeclared or unknown capabilities fail closed."""
    valid_manifest_dict["capabilities"] = ["filesystem_read", "super_admin_root"]
    with pytest.raises(
        ManifestValidationError, match="Unknown plugin capability 'super_admin_root'"
    ):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


# ---------------------------------------------------------------------------
# 8. Tool Declarations & Builtin Shadowing Protection
# ---------------------------------------------------------------------------


def test_reject_duplicate_tools_in_manifest(valid_manifest_dict: dict[str, Any]) -> None:
    """Verify duplicate tool names in same manifest fail closed."""
    valid_manifest_dict["tools"] = ["status", "diff", "status"]
    with pytest.raises(ManifestValidationError, match="Duplicate tool declaration 'status'"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


@pytest.mark.parametrize(
    "builtin_tool",
    [
        "calculator",
        "read_file",
        "delete_file",
        "modify_code",
        "apply_patch",
        "run_tests",
        "browser_navigate",
    ],
)
def test_reject_shadowing_builtin_tools(
    valid_manifest_dict: dict[str, Any], builtin_tool: str
) -> None:
    """Verify plugin cannot declare a tool that collides with a built-in ECHO tool."""
    valid_manifest_dict["tools"] = [builtin_tool]
    with pytest.raises(ManifestValidationError, match="collides with a built-in ECHO system tool"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)


@pytest.mark.parametrize(
    "bad_tool_name",
    [
        "git.status",  # Must not contain dots
        "status/diff",  # Must not contain slashes
        "Status",  # No uppercase
        "my tool",  # No spaces
    ],
)
def test_reject_invalid_tool_names(valid_manifest_dict: dict[str, Any], bad_tool_name: str) -> None:
    """Verify tool names with illegal characters fail closed."""
    valid_manifest_dict["tools"] = [bad_tool_name]
    with pytest.raises(ManifestValidationError, match="illegal separator characters|invalid"):
        PluginManifestValidator.parse_and_validate(valid_manifest_dict)
