from packages.common.capability_registry import capability_registry
from packages.common.tool_registry import tool_registry
from services.brain.tools import register_builtin_tools


def test_builtin_tools_are_registered_as_capabilities():
    register_builtin_tools()

    assert capability_registry.is_available("calculator")
    assert capability_registry.is_available("time")
    assert capability_registry.is_available("date")


def test_builtin_tool_capabilities_match_registered_tools():
    register_builtin_tools()

    for tool_name in ("calculator", "time", "date"):
        assert tool_registry.get(tool_name) is not None
        assert capability_registry.get(tool_name) is not None


def test_terminal_is_not_registered_as_a_capability():
    register_builtin_tools()

    assert capability_registry.is_available("terminal") is False


def test_builtin_capability_has_description():
    register_builtin_tools()

    calculator = capability_registry.get("calculator")

    assert calculator is not None
    assert calculator.description
    assert calculator.available is True