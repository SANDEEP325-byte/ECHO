from packages.common.capability_registry import (
    Capability,
    CapabilityRegistry,
)


def test_capability_can_be_registered():
    registry = CapabilityRegistry()

    capability = Capability(
        name="calculator",
        description="Performs mathematical calculations.",
    )

    registry.register(capability)

    assert registry.get("calculator") == capability


def test_registered_capability_is_available():
    registry = CapabilityRegistry()

    registry.register(
        Capability(
            name="calculator",
            description="Performs mathematical calculations.",
        )
    )

    assert registry.is_available("calculator") is True


def test_unregistered_capability_is_unavailable():
    registry = CapabilityRegistry()

    assert registry.is_available("terminal") is False


def test_disabled_capability_is_unavailable():
    registry = CapabilityRegistry()

    registry.register(
        Capability(
            name="terminal",
            description="Executes terminal commands.",
            available=False,
        )
    )

    assert registry.is_available("terminal") is False


def test_get_available_returns_only_available_capabilities():
    registry = CapabilityRegistry()

    registry.register(
        Capability(
            name="calculator",
            description="Performs calculations.",
        )
    )

    registry.register(
        Capability(
            name="terminal",
            description="Executes terminal commands.",
            available=False,
        )
    )

    available = registry.get_available()

    assert len(available) == 1
    assert available[0].name == "calculator"


def test_get_all_returns_all_capabilities():
    registry = CapabilityRegistry()

    registry.register(
        Capability(
            name="calculator",
            description="Performs calculations.",
        )
    )

    registry.register(
        Capability(
            name="terminal",
            description="Executes terminal commands.",
            available=False,
        )
    )

    capabilities = registry.get_all()

    assert len(capabilities) == 2