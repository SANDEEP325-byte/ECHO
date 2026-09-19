"""Plugin architecture interfaces and contracts for ECHO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.interfaces.tool import Tool


class PluginCapability(str, Enum):
    """Deterministic, closed set of declared plugin capabilities.

    IMPORTANT: Declaring a capability is NOT a permission grant.
    ECHO's SecurityEngine and PermissionManager remain authoritative for all operations.
    """

    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    TERMINAL_EXECUTE = "terminal_execute"
    BROWSER_ACCESS = "browser_access"
    NETWORK_ACCESS = "network_access"
    SYSTEM_INFO = "system_info"
    AUTOMATION = "automation"


class PluginState(str, Enum):
    """Lifecycle states for local ECHO plugins."""

    DISCOVERED = "discovered"
    VALIDATED = "validated"
    LOADED = "loaded"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True)
class PluginMetadata:
    """Immutable metadata extracted from a validated plugin manifest."""

    id: str
    name: str
    version: str
    description: str
    author: str
    entrypoint: str
    min_echo_version: str
    capabilities: tuple[PluginCapability, ...]
    tools: tuple[str, ...]
    max_echo_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to a serializable dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "entrypoint": self.entrypoint,
            "min_echo_version": self.min_echo_version,
            "max_echo_version": self.max_echo_version,
            "capabilities": [c.value for c in self.capabilities],
            "tools": list(self.tools),
        }


@dataclass(frozen=True)
class PluginManifest:
    """Container for a validated plugin manifest."""

    metadata: PluginMetadata

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version

    @property
    def entrypoint(self) -> str:
        return self.metadata.entrypoint

    @property
    def capabilities(self) -> tuple[PluginCapability, ...]:
        return self.metadata.capabilities

    @property
    def tools(self) -> tuple[str, ...]:
        return self.metadata.tools

    def to_dict(self) -> dict[str, Any]:
        return self.metadata.to_dict()


class Plugin(ABC):
    """Base abstract interface that every ECHO plugin must implement.

    CRITICAL SECURITY NOTE:
    Plugins run in-process. importlib loading executes Python code in the host process.
    Catching import/execution exceptions provides fault isolation only, NOT security sandboxing.
    All local plugins must be explicitly enabled and treated as trusted code execution.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the plugin resources. Called upon loading."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release plugin resources. Called upon disabling or unloading."""

    @abstractmethod
    def get_tools(self) -> list[Tool]:
        """Return the list of Tool instances provided by this plugin.

        Every tool returned must have its bare name declared in manifest.tools.
        The PluginManager will namespace these tools as '<plugin_id>.<tool_name>'.
        """
