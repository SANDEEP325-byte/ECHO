"""ECHO Plugin System package."""

from services.plugins.loader import PluginLoader, PluginLoadError
from services.plugins.manager import (
    NamespacedPluginTool,
    PluginManager,
    PluginRecord,
    plugin_manager,
)
from services.plugins.manifest import ManifestValidationError, PluginManifestValidator
from services.plugins.security_policy import PluginSecurityPolicy

__all__ = [
    "ManifestValidationError",
    "NamespacedPluginTool",
    "PluginLoadError",
    "PluginLoader",
    "PluginManager",
    "PluginManifestValidator",
    "PluginRecord",
    "PluginSecurityPolicy",
    "plugin_manager",
]
