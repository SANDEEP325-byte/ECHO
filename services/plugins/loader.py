"""Isolated dynamic loader for local ECHO plugins."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from packages.interfaces.plugin import Plugin, PluginManifest
from services.logging.logger import logger  # type: ignore[attr-defined]


class PluginLoadError(Exception):
    """Raised when plugin loading, importation, or initialization fails."""


class PluginLoader:
    """Dynamically loads and instantiates local ECHO plugins.

    ===========================================================================
    CRITICAL SECURITY REQUIREMENT:
    `importlib` loading is NOT a security sandbox.
    Python code executes directly in the host ECHO process when imported.
    Catching exceptions provides fault isolation only, NOT malicious-code containment.
    Only explicitly enabled and trusted local plugins must ever be loaded.
    Process-level sandboxing (Docker/WASM) is strictly out of scope for Phase 8A/8B.
    ===========================================================================
    """

    @classmethod
    def load_plugin(cls, plugin_dir: Path, manifest: PluginManifest) -> Plugin:
        """Load a plugin module and instantiate its Plugin subclass.

        Fault-isolated: Catches and wraps syntax, import, and initialization errors
        to prevent a single broken plugin from crashing the ECHO host process.
        """
        resolved_plugin_dir = plugin_dir.resolve()
        entrypoint_file = (resolved_plugin_dir / manifest.entrypoint).resolve()

        # Enforce that entrypoint strictly resides within the plugin directory
        try:
            entrypoint_file.relative_to(resolved_plugin_dir)
        except ValueError as exc:
            raise PluginLoadError(
                f"Security violation: entrypoint '{manifest.entrypoint}' escapes plugin directory '{plugin_dir}'."
            ) from exc

        if not entrypoint_file.is_file():
            raise PluginLoadError(
                f"Plugin entrypoint file '{manifest.entrypoint}' does not exist in '{plugin_dir}'."
            )

        module_name = f"echo_plugin_{manifest.id}"

        logger.info(
            "Loading plugin module: id='{}', path='{}'",
            manifest.id,
            entrypoint_file,
        )

        try:
            spec = importlib.util.spec_from_file_location(module_name, entrypoint_file)
            if spec is None or spec.loader is None:
                raise PluginLoadError(
                    f"Failed to create module spec for plugin '{manifest.id}' from '{entrypoint_file}'."
                )

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            # Execute module to load plugin classes (Fault isolated)
            spec.loader.exec_module(module)

        except Exception as exc:
            sys.modules.pop(module_name, None)
            logger.error("Failed to import plugin '{}': {}", manifest.id, exc)
            raise PluginLoadError(f"Import error in plugin '{manifest.id}': {exc}") from exc

        # Find the Plugin implementation
        plugin_class: type[Plugin] | None = None
        for _attr_name, attr_value in inspect.getmembers(module, inspect.isclass):
            if issubclass(attr_value, Plugin) and attr_value is not Plugin:
                plugin_class = attr_value
                break

        if plugin_class is None:
            sys.modules.pop(module_name, None)
            raise PluginLoadError(
                f"No subclass of 'Plugin' found in entrypoint '{manifest.entrypoint}' for plugin '{manifest.id}'."
            )

        # Instantiate and initialize (Fault isolated)
        try:
            plugin_instance = plugin_class(manifest=manifest)
            plugin_instance.initialize()
            return plugin_instance
        except Exception as exc:
            sys.modules.pop(module_name, None)
            logger.error("Initialization failed for plugin '{}': {}", manifest.id, exc)
            raise PluginLoadError(
                f"Initialization failed for plugin '{manifest.id}': {exc}"
            ) from exc
