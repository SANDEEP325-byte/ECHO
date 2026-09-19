from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    available: bool = True


class CapabilityRegistry:
    """Registry of capabilities currently available to ECHO."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.name] = capability

    def unregister(self, name: str) -> bool:
        """Unregister a capability by name. Returns True if removed, False otherwise."""
        if name in self._capabilities:
            del self._capabilities[name]
            return True
        return False

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def is_available(self, name: str) -> bool:
        capability = self.get(name)

        if capability is None:
            return False

        return capability.available

    def get_available(self) -> list[Capability]:
        return [capability for capability in self._capabilities.values() if capability.available]

    def get_all(self) -> list[Capability]:
        return list(self._capabilities.values())


capability_registry = CapabilityRegistry()
