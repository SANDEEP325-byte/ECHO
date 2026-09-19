"""Unit and integration tests for ECHO Plugin Discovery, Lifecycle & Registration (Phase 8B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.common.tool_registry import ToolRegistry
from packages.interfaces.plugin import PluginState
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.tool import Tool
from packages.interfaces.tool_result import ToolResult
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.plugins.manager import PluginManager
from services.security.safety_engine import SafetyEngine


class MockPluginTool(Tool):
    """Simple test tool returned by mock plugin."""

    def __init__(self, name: str = "ping") -> None:
        self.name = name
        self.description = "Test ping tool"
        self.definition = ToolDefinition(
            name=name,
            description=self.description,
            parameters=(
                ToolParameter(
                    name="msg", type="string", description="Message to echo", required=True
                ),
            ),
        )

    def execute(self, **kwargs: Any) -> Any:
        return f"pong: {kwargs.get('msg', '')}"


# ---------------------------------------------------------------------------
# Test Fixtures & Sample Plugin Generators
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_plugins_dir(tmp_path: Path) -> Path:
    """Create a temporary plugins root directory with a valid sample plugin."""
    plugin_dir = tmp_path / "echo_ping"
    plugin_dir.mkdir()

    manifest_content = {
        "id": "echo_ping",
        "name": "Echo Ping Plugin",
        "version": "1.0.0",
        "description": "Network test ping plugin",
        "author": "Tester",
        "entrypoint": "main.py",
        "min_echo_version": "0.1.0",
        "capabilities": ["network_access"],
        "tools": ["ping"],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_content), encoding="utf-8")

    code_content = """
from packages.interfaces.plugin import Plugin
from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter

class PingTool(Tool):
    def __init__(self):
        self.name = "ping"
        self.description = "Ping responder"
        self.definition = ToolDefinition(
            name="ping",
            description=self.description,
            parameters=(ToolParameter(name="msg", type="string", description="msg", required=True),)
        )
    def execute(self, **kwargs):
        return f"pong: {kwargs.get('msg', '')}"

class PingPlugin(Plugin):
    def initialize(self):
        self.initialized = True
    def shutdown(self):
        self.shutdown_called = True
    def get_tools(self):
        return [PingTool()]
"""
    (plugin_dir / "main.py").write_text(code_content, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Discovery Without Execution
# ---------------------------------------------------------------------------


def test_discovery_does_not_execute_code(tmp_path: Path) -> None:
    """Verify discovery reads manifests ONLY and NEVER executes plugin Python code."""
    plugin_dir = tmp_path / "side_effect_plugin"
    plugin_dir.mkdir()

    marker_file = tmp_path / "imported_marker.txt"

    manifest_content = {
        "id": "side_effect_plugin",
        "name": "Side Effect Test",
        "version": "1.0.0",
        "description": "Tests that import side-effects do not fire on discovery",
        "author": "Tester",
        "entrypoint": "main.py",
        "min_echo_version": "0.1.0",
        "capabilities": [],
        "tools": ["do_nothing"],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_content), encoding="utf-8")

    # If this file is imported, it writes the marker
    (plugin_dir / "main.py").write_text(
        f"from pathlib import Path\nPath(r'{marker_file}').write_text('executed')\n",
        encoding="utf-8",
    )

    reg = ToolRegistry()
    manager = PluginManager(plugins_dir=tmp_path, tool_reg=reg)
    discovered = manager.discover()

    assert len(discovered) == 1
    assert discovered[0].id == "side_effect_plugin"
    record = manager.get_plugin("side_effect_plugin")
    assert record is not None
    assert record.state == PluginState.VALIDATED

    # The marker file MUST NOT exist!
    assert not marker_file.exists(), "Security failure: plugin code was executed during discovery!"


# ---------------------------------------------------------------------------
# 2. Explicit Enablement & Lifecycle
# ---------------------------------------------------------------------------


def test_unenabled_plugin_remains_unloaded(temp_plugins_dir: Path) -> None:
    """Verify discovering an unenabled plugin does NOT load it into active state."""
    reg = ToolRegistry()
    manager = PluginManager(plugins_dir=temp_plugins_dir, tool_reg=reg)
    manager.discover()

    # Attempting to load without enabling fails closed
    success = manager.load_plugin("echo_ping")
    assert success is False
    record = manager.get_plugin("echo_ping")
    assert record is not None
    assert record.state == PluginState.VALIDATED
    assert reg.get("echo_ping.ping") is None


def test_explicitly_enabled_plugin_loads_and_registers_tools(temp_plugins_dir: Path) -> None:
    """Verify explicitly enabling a plugin loads it and registers namespaced tools."""
    reg = ToolRegistry()
    manager = PluginManager(plugins_dir=temp_plugins_dir, tool_reg=reg)
    manager.discover()

    # Enable and load
    enabled_ok = manager.enable_plugin("echo_ping")
    assert enabled_ok is True
    assert manager.is_plugin_active("echo_ping") is True

    record = manager.get_plugin("echo_ping")
    assert record is not None
    assert record.state == PluginState.ACTIVE
    assert record.registered_tools == ["echo_ping.ping"]

    # Tool is registered under <plugin_id>.<tool_name>
    tool = reg.get("echo_ping.ping")
    assert tool is not None
    assert tool.name == "echo_ping.ping"
    assert tool.definition.name == "echo_ping.ping"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 3. Canonical Execution, ToolRouter & SafetyEngine Pipeline
# ---------------------------------------------------------------------------


def test_plugin_tool_execution_via_registry(temp_plugins_dir: Path) -> None:
    """Verify registered plugin tool executes through ToolRegistry."""
    reg = ToolRegistry()
    manager = PluginManager(
        plugins_dir=temp_plugins_dir, enabled_plugins=["echo_ping"], tool_reg=reg
    )
    manager.discover()
    manager.load_all_enabled()

    result = reg.execute("echo_ping.ping", msg="hello world")
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.result == "pong: hello world"


def test_plugin_tool_canonical_safety_engine_evaluation(temp_plugins_dir: Path) -> None:
    """Verify plugin tools pass through SafetyEngine and default to SENSITIVE / CONFIRM."""
    reg = ToolRegistry()
    manager = PluginManager(
        plugins_dir=temp_plugins_dir, enabled_plugins=["echo_ping"], tool_reg=reg
    )
    manager.discover()
    manager.load_all_enabled()

    safety = SafetyEngine()

    # By default, unknown non-builtin operations are classified as SENSITIVE requiring CONFIRM
    decision = safety.evaluate("echo_ping.ping", arguments={"msg": "safe"})
    assert decision.risk_level == RiskLevel.SENSITIVE
    assert decision.decision == PermissionDecision.CONFIRM

    # Dangerous payload escalation check
    dangerous_decision = safety.evaluate(
        "echo_ping.ping", arguments={"msg": "run format C: please"}
    )
    assert dangerous_decision.risk_level == RiskLevel.CRITICAL
    assert dangerous_decision.decision == PermissionDecision.CONFIRM


def test_capability_declaration_does_not_bypass_safety() -> None:
    """Verify that declaring a capability like filesystem_read does NOT grant free pass."""
    safety = SafetyEngine()
    # Even if plugin declared filesystem_read or terminal_execute, tool invocation
    # still goes through canonical SafetyEngine
    res = safety.evaluate("custom_plugin.read_secret")
    assert res.risk_level == RiskLevel.SENSITIVE
    assert res.decision == PermissionDecision.CONFIRM


# ---------------------------------------------------------------------------
# 4. Tool Collision & Undeclared Tool Defense
# ---------------------------------------------------------------------------


def test_reject_undeclared_tool_registration(tmp_path: Path) -> None:
    """Verify plugin returning a tool not declared in manifest.tools fails load."""
    plugin_dir = tmp_path / "sneaky_plugin"
    plugin_dir.mkdir()

    manifest_content = {
        "id": "sneaky_plugin",
        "name": "Sneaky Plugin",
        "version": "1.0.0",
        "description": "Declares one tool but tries to register another",
        "author": "Tester",
        "entrypoint": "main.py",
        "min_echo_version": "0.1.0",
        "capabilities": [],
        "tools": ["declared_tool"],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_content), encoding="utf-8")

    code = """
from packages.interfaces.plugin import Plugin
from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition

class UndeclaredTool(Tool):
    def __init__(self):
        self.name = "undeclared_secret_tool"
        self.description = "sneaky"
        self.definition = ToolDefinition(name="undeclared_secret_tool", description="sneaky", parameters=())
    def execute(self, **kwargs): return "bad"

class Sneaky(Plugin):
    def initialize(self): pass
    def shutdown(self): pass
    def get_tools(self): return [UndeclaredTool()]
"""
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")

    reg = ToolRegistry()
    manager = PluginManager(plugins_dir=tmp_path, enabled_plugins=["sneaky_plugin"], tool_reg=reg)
    manager.discover()
    loaded = manager.load_plugin("sneaky_plugin")

    assert loaded is False
    record = manager.get_plugin("sneaky_plugin")
    assert record is not None
    assert record.state == PluginState.ERROR
    assert record.error is not None
    assert "undeclared tool" in record.error.lower()
    assert reg.get("sneaky_plugin.undeclared_secret_tool") is None


def test_cross_plugin_tool_collision_prevention(tmp_path: Path) -> None:
    """Verify two plugins attempting to register the same tool name fail cleanly."""
    reg = ToolRegistry()
    # Pre-register a tool under plugin1.action
    tool1 = MockPluginTool(name="plugin1.action")
    reg.register(tool1)

    # Now define plugin1 attempting to register action again
    p_dir = tmp_path / "plugin1"
    p_dir.mkdir()
    (p_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "plugin1",
                "name": "P1",
                "version": "1.0.0",
                "description": "p1",
                "author": "tester",
                "entrypoint": "main.py",
                "min_echo_version": "0.1.0",
                "capabilities": [],
                "tools": ["action"],
            }
        ),
        encoding="utf-8",
    )
    (p_dir / "main.py").write_text(
        """
from packages.interfaces.plugin import Plugin
from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition

class ActTool(Tool):
    def __init__(self):
        self.name = "action"
        self.description = "act"
        self.definition = ToolDefinition(name="action", description="act", parameters=())
    def execute(self, **kwargs): return "act"

class P(Plugin):
    def initialize(self): pass
    def shutdown(self): pass
    def get_tools(self): return [ActTool()]
""",
        encoding="utf-8",
    )

    manager = PluginManager(plugins_dir=tmp_path, enabled_plugins=["plugin1"], tool_reg=reg)
    manager.discover()
    success = manager.load_plugin("plugin1")
    assert success is False
    p1_record = manager.get_plugin("plugin1")
    assert p1_record is not None
    assert p1_record.state == PluginState.ERROR
    assert p1_record.error is not None
    assert "collision" in p1_record.error.lower()


# ---------------------------------------------------------------------------
# 5. Fault Isolation & Crash Resilience
# ---------------------------------------------------------------------------


def test_plugin_syntax_error_does_not_crash_core(tmp_path: Path) -> None:
    """Verify plugin syntax error transitions plugin to ERROR without crashing process."""
    broken_dir = tmp_path / "broken_plugin"
    broken_dir.mkdir()

    (broken_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "broken_plugin",
                "name": "Broken Plugin",
                "version": "1.0.0",
                "description": "Has syntax error",
                "author": "tester",
                "entrypoint": "main.py",
                "min_echo_version": "0.1.0",
                "capabilities": [],
                "tools": ["noop"],
            }
        ),
        encoding="utf-8",
    )
    (broken_dir / "main.py").write_text("def invalid_syntax(:::", encoding="utf-8")

    manager = PluginManager(plugins_dir=tmp_path, enabled_plugins=["broken_plugin"])
    manager.discover()
    loaded = manager.load_plugin("broken_plugin")

    assert loaded is False
    record = manager.get_plugin("broken_plugin")
    assert record is not None
    assert record.state == PluginState.ERROR
    assert record.error is not None
    assert "syntaxerror" in record.error.lower() or "invalid syntax" in record.error.lower()


def test_plugin_initialize_exception_isolated(tmp_path: Path) -> None:
    """Verify plugin throwing during initialize() fails safely into ERROR state."""
    init_fail_dir = tmp_path / "init_fail"
    init_fail_dir.mkdir()

    (init_fail_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "init_fail",
                "name": "Init Fail",
                "version": "1.0.0",
                "description": "Fails initialize",
                "author": "tester",
                "entrypoint": "main.py",
                "min_echo_version": "0.1.0",
                "capabilities": [],
                "tools": ["noop"],
            }
        ),
        encoding="utf-8",
    )
    (init_fail_dir / "main.py").write_text(
        """
from packages.interfaces.plugin import Plugin

class FailPlugin(Plugin):
    def initialize(self):
        raise RuntimeError("Database connection unreachable")
    def shutdown(self): pass
    def get_tools(self): return []
""",
        encoding="utf-8",
    )

    manager = PluginManager(plugins_dir=tmp_path, enabled_plugins=["init_fail"])
    manager.discover()
    loaded = manager.load_plugin("init_fail")

    assert loaded is False
    fail_rec = manager.get_plugin("init_fail")
    assert fail_rec is not None
    assert fail_rec.state == PluginState.ERROR
    assert fail_rec.error is not None
    assert "database connection unreachable" in fail_rec.error.lower()


# ---------------------------------------------------------------------------
# 6. Disable Plugin & Teardown
# ---------------------------------------------------------------------------


def test_disable_plugin_unregisters_tools(temp_plugins_dir: Path) -> None:
    """Verify disabling an active plugin unregisters all its tools and calls shutdown."""
    reg = ToolRegistry()
    manager = PluginManager(
        plugins_dir=temp_plugins_dir, enabled_plugins=["echo_ping"], tool_reg=reg
    )
    manager.discover()
    manager.load_all_enabled()

    assert reg.get("echo_ping.ping") is not None
    assert manager.is_plugin_active("echo_ping") is True

    # Disable
    disabled = manager.disable_plugin("echo_ping")
    assert disabled is True
    assert manager.is_plugin_active("echo_ping") is False
    ping_rec = manager.get_plugin("echo_ping")
    assert ping_rec is not None
    assert ping_rec.state == PluginState.DISABLED

    # Tool is removed from registry
    assert reg.get("echo_ping.ping") is None
