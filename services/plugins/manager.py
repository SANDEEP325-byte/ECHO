"""PluginManager coordinating discovery, lifecycle, and namespaced tool registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.common.capability_registry import (
    Capability,
    CapabilityRegistry,
)
from packages.common.capability_registry import (
    capability_registry as default_capability_registry,
)
from packages.common.tool_registry import ToolRegistry
from packages.common.tool_registry import tool_registry as default_tool_registry
from packages.interfaces.plugin import Plugin, PluginManifest, PluginState
from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.plugins.loader import PluginLoader, PluginLoadError
from services.plugins.manifest import ManifestValidationError, PluginManifestValidator
from services.security.pending_action_manager import (
    PendingActionManager,
)
from services.security.pending_action_manager import (
    pending_action_manager as default_pending_action_manager,
)


class NamespacedPluginTool(Tool):
    """Wrapper that enforces `<plugin_id>.<tool_name>` namespacing on plugin tools."""

    def __init__(self, plugin_id: str, inner_tool: Tool, bare_name: str) -> None:
        self.plugin_id = plugin_id
        self.inner_tool = inner_tool
        self.bare_name = bare_name
        self.name = f"{plugin_id}.{bare_name}"
        self.description = getattr(inner_tool, "description", "")
        inner_def = getattr(inner_tool, "definition", None)
        if inner_def is None or not isinstance(inner_def, ToolDefinition):
            raise TypeError(
                f"Plugin tool '{self.name}' must define a valid ToolDefinition instance."
            )
        self.definition = ToolDefinition(
            name=self.name,
            description=inner_def.description,
            parameters=tuple(inner_def.parameters) if inner_def.parameters else (),
        )

    def execute(self, **kwargs: Any) -> Any:
        return self.inner_tool.execute(**kwargs)


@dataclass
class PluginRecord:
    """Tracks the state and metadata of a discovered or loaded plugin."""

    id: str
    manifest: PluginManifest
    plugin_dir: Path
    state: PluginState
    plugin_instance: Plugin | None = None
    registered_tools: list[str] | None = None
    error: str | None = None
    consecutive_failures: int = 0
    max_consecutive_failures: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.manifest.name,
            "version": self.manifest.version,
            "state": self.state.value,
            "capabilities": [c.value for c in self.manifest.capabilities],
            "tools": list(self.manifest.tools),
            "registered_tools": self.registered_tools or [],
            "error": self.error,
            "consecutive_failures": self.consecutive_failures,
        }


class PluginManager:
    """Manages the full lifecycle of local ECHO plugins.

    Core Philosophy:
    - Discovery does NOT execute plugin code (inspects manifest.json only).
    - Plugins are not loaded unless explicitly enabled.
    - Plugin tools are strictly namespaced as `<plugin_id>.<tool_name>`.
    - Collisions with built-in tools or other plugins fail closed.
    - Runtime and import failures are fault-isolated without crashing Core.
    """

    def __init__(
        self,
        plugins_dir: Path | str | None = None,
        enabled_plugins: set[str] | list[str] | None = None,
        tool_reg: ToolRegistry | None = None,
        capability_reg: CapabilityRegistry | None = None,
        pending_action_mgr: PendingActionManager | None = None,
        current_echo_version: str | None = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir or "plugins").resolve()
        self.enabled_plugins: set[str] = set(enabled_plugins or [])
        self.tool_registry: ToolRegistry = tool_reg or default_tool_registry
        self.capability_registry: CapabilityRegistry = capability_reg or default_capability_registry
        self.pending_action_manager: PendingActionManager = (
            pending_action_mgr or default_pending_action_manager
        )
        self.current_echo_version = current_echo_version
        self._plugins: dict[str, PluginRecord] = {}

    def discover(self) -> list[PluginManifest]:
        """Discover plugins in the plugins directory by inspecting manifests only.

        CRITICAL: Never executes Python code during discovery. Only reads manifest.json.
        """
        discovered: list[PluginManifest] = []

        if not self.plugins_dir.exists() or not self.plugins_dir.is_dir():
            logger.info(
                "Plugins directory '{}' does not exist or is not a directory", self.plugins_dir
            )
            return discovered

        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue

            manifest_file = entry / "manifest.json"
            if not manifest_file.is_file():
                continue

            try:
                raw_content = manifest_file.read_text(encoding="utf-8")
                manifest = PluginManifestValidator.parse_and_validate(
                    raw_content,
                    current_echo_version=self.current_echo_version,
                )

                # Check duplicate plugin ID across discovered folders
                if manifest.id in self._plugins:
                    existing = self._plugins[manifest.id]
                    raise ManifestValidationError(
                        f"Duplicate plugin ID '{manifest.id}' found in '{entry}' "
                        f"(already registered from '{existing.plugin_dir}')."
                    )

                record = PluginRecord(
                    id=manifest.id,
                    manifest=manifest,
                    plugin_dir=entry,
                    state=PluginState.VALIDATED,
                )
                self._plugins[manifest.id] = record
                discovered.append(manifest)
                logger.info("Discovered and validated plugin '{}' at '{}'", manifest.id, entry)

            except Exception as exc:  # noqa: BLE001
                err_msg = f"Failed to discover plugin at '{entry}': {exc}"
                logger.error(err_msg)
                # If ID is discernible from directory name, register record in ERROR state
                dummy_id = entry.name.lower()
                if dummy_id not in self._plugins:
                    # Create a minimal record tracking error
                    self._plugins[dummy_id] = PluginRecord(
                        id=dummy_id,
                        manifest=PluginManifestValidator.parse_and_validate(
                            {
                                "id": dummy_id
                                if PluginManifestValidator.ID_PATTERN.fullmatch(dummy_id)
                                else "invalid",
                                "name": dummy_id,
                                "version": "0.0.0",
                                "description": "Failed discovery",
                                "author": "unknown",
                                "entrypoint": "main.py",
                                "min_echo_version": "0.1.0",
                                "capabilities": [],
                                "tools": [],
                            }
                        )
                        if PluginManifestValidator.ID_PATTERN.fullmatch(dummy_id)
                        and dummy_id not in PluginManifestValidator.RESERVED_IDS
                        else None,  # type: ignore[arg-type]
                        plugin_dir=entry,
                        state=PluginState.ERROR,
                        error=str(exc),
                    )

        return discovered

    def enable_plugin(self, plugin_id: str, load_immediately: bool = True) -> bool:
        """Mark a plugin as explicitly enabled and optionally load it."""
        self.enabled_plugins.add(plugin_id)
        if load_immediately and plugin_id in self._plugins:
            record = self._plugins[plugin_id]
            if record.state in (
                PluginState.DISCOVERED,
                PluginState.VALIDATED,
                PluginState.DISABLED,
            ):
                return self.load_plugin(plugin_id)
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable an active plugin, shut it down, and unregister its tools."""
        self.enabled_plugins.discard(plugin_id)

        record = self._plugins.get(plugin_id)
        if not record:
            return False

        # 1. Unregister all tools from canonical ToolRegistry and CapabilityRegistry
        if record.registered_tools:
            for tool_name in record.registered_tools:
                self.tool_registry.unregister(tool_name)
                self.capability_registry.unregister(tool_name)
            record.registered_tools = []

        # 2. Invalidate any pending confirmation actions for this plugin
        self.pending_action_manager.cancel_actions_for_plugin(plugin_id)

        # 3. Call shutdown on plugin instance
        if record.plugin_instance:
            try:
                record.plugin_instance.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error during shutdown of plugin '{}': {}", plugin_id, exc)

        record.state = PluginState.DISABLED
        logger.info("Plugin '{}' disabled and tools unregistered", plugin_id)
        return True

    def load_plugin(self, plugin_id: str) -> bool:
        """Load an explicitly enabled plugin and register its tools.

        Guarantees:
        - Plugin must be in enabled_plugins set.
        - Namespaces every tool as `<plugin_id>.<tool_name>`.
        - Registers tools in ToolRegistry and CapabilityRegistry.
        - Catches all import/runtime exceptions to provide fault isolation.
        """
        record = self._plugins.get(plugin_id)
        if not record:
            logger.warning("Cannot load unknown plugin '{}'", plugin_id)
            return False

        if plugin_id not in self.enabled_plugins:
            logger.warning(
                "Plugin '{}' is not explicitly enabled. Untrusted plugins remain unloaded.",
                plugin_id,
            )
            return False

        if record.manifest is None:
            logger.error("Cannot load plugin '{}': invalid manifest", plugin_id)
            record.state = PluginState.ERROR
            return False

        try:
            # 1. Isolated load
            plugin_instance = PluginLoader.load_plugin(
                plugin_dir=record.plugin_dir,
                manifest=record.manifest,
            )

            # 2. Extract tools
            tools = plugin_instance.get_tools()
            if not isinstance(tools, list):
                raise PluginLoadError(
                    f"Plugin '{plugin_id}'.get_tools() must return a list of Tool instances."
                )

            registered_names: list[str] = []
            declared_tools = set(record.manifest.tools)

            for tool in tools:
                if not isinstance(tool, Tool):
                    raise PluginLoadError(
                        f"Object '{tool}' returned by plugin '{plugin_id}' is not an instance of Tool."
                    )

                # Determine bare tool name
                bare_name = tool.name
                if bare_name.startswith(f"{plugin_id}."):
                    bare_name = bare_name[len(plugin_id) + 1 :]

                if bare_name not in declared_tools:
                    raise PluginLoadError(
                        f"Plugin '{plugin_id}' attempted to register undeclared tool '{bare_name}'. "
                        f"Declared tools in manifest: {sorted(declared_tools)}."
                    )

                namespaced_name = f"{plugin_id}.{bare_name}"

                # Collision checks
                if namespaced_name in PluginManifestValidator.BUILTIN_TOOLS:
                    raise PluginLoadError(
                        f"Namespaced tool '{namespaced_name}' collides with built-in tool."
                    )

                existing_tool = self.tool_registry.get(namespaced_name)
                if existing_tool is not None:
                    raise PluginLoadError(
                        f"Tool collision: tool '{namespaced_name}' is already registered."
                    )

                wrapped_tool = NamespacedPluginTool(
                    plugin_id=plugin_id,
                    inner_tool=tool,
                    bare_name=bare_name,
                )
                self.tool_registry.register(wrapped_tool)
                self.capability_registry.register(
                    Capability(
                        name=namespaced_name,
                        description=wrapped_tool.description,
                    )
                )
                registered_names.append(namespaced_name)

            record.plugin_instance = plugin_instance
            record.registered_tools = registered_names
            record.state = PluginState.ACTIVE
            record.error = None
            record.consecutive_failures = 0
            logger.info(
                "Plugin '{}' loaded successfully with {} tool(s): {}",
                plugin_id,
                len(registered_names),
                registered_names,
            )
            return True

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load plugin '{}': {}", plugin_id, exc)
            record.state = PluginState.ERROR
            record.error = str(exc)

            # Roll back any partially registered tools for this plugin
            if record.registered_tools:
                for tool_name in record.registered_tools:
                    self.tool_registry.unregister(tool_name)
                    self.capability_registry.unregister(tool_name)
                record.registered_tools = []

            return False

    def load_all_enabled(self) -> dict[str, bool]:
        """Attempt to load all discovered plugins that are marked enabled."""
        results: dict[str, bool] = {}
        for plugin_id in sorted(self.enabled_plugins):
            if plugin_id in self._plugins:
                results[plugin_id] = self.load_plugin(plugin_id)
        return results

    def get_plugin(self, plugin_id: str) -> PluginRecord | None:
        """Retrieve the record of a registered plugin."""
        return self._plugins.get(plugin_id)

    def is_plugin_active(self, plugin_id: str) -> bool:
        """Check if a plugin is currently in ACTIVE state."""
        record = self._plugins.get(plugin_id)
        return record is not None and record.state == PluginState.ACTIVE

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return serializable summary of all known plugins."""
        return [record.to_dict() for record in self._plugins.values()]

    def record_failure(self, plugin_id: str, error: str) -> None:
        """Record a failure for an active plugin and trigger circuit breaker if threshold reached."""
        record = self._plugins.get(plugin_id)
        if not record:
            return

        record.consecutive_failures += 1
        logger.warning(
            "Plugin '{}' recorded failure ({}/{}): {}",
            plugin_id,
            record.consecutive_failures,
            record.max_consecutive_failures,
            error,
        )

        if record.consecutive_failures >= record.max_consecutive_failures:
            logger.error(
                "Plugin '{}' exceeded failure threshold ({}); quarantining plugin.",
                plugin_id,
                record.max_consecutive_failures,
            )
            self.disable_plugin(plugin_id)
            record.state = PluginState.ERROR
            record.error = (
                f"Quarantined: exceeded maximum consecutive failures "
                f"({record.max_consecutive_failures}). Last error: {error}"
            )

    def record_success(self, plugin_id: str) -> None:
        """Reset consecutive failure counter on successful plugin tool execution."""
        record = self._plugins.get(plugin_id)
        if record:
            record.consecutive_failures = 0

    def check_health(self, plugin_id: str) -> bool:
        """Check the health of an active plugin."""
        record = self._plugins.get(plugin_id)
        if not record or record.state != PluginState.ACTIVE or not record.plugin_instance:
            return False

        try:
            is_healthy = record.plugin_instance.health_check()
            if not is_healthy:
                self.record_failure(plugin_id, "Health check failed (returned False)")
                return False
            self.record_success(plugin_id)
            return True
        except Exception as exc:  # noqa: BLE001
            self.record_failure(plugin_id, f"Health check exception: {exc}")
            return False


plugin_manager = PluginManager()
