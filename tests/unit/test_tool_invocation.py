import pytest

from packages.interfaces.tool_invocation import ToolInvocation


def test_valid_tool_invocation_creation():
    invocation = ToolInvocation(
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
        purpose="Compute the sum of two integers",
        step_number=1,
    )

    assert invocation.tool_name == "calculator"
    assert invocation.arguments == {"expression": "10 + 20"}
    assert invocation.purpose == "Compute the sum of two integers"
    assert invocation.step_number == 1


def test_tool_invocation_normalizes_tool_name():
    invocation = ToolInvocation(
        tool_name="  CALCULATOR  ",
        arguments={"expression": "5 * 5"},
    )

    assert invocation.tool_name == "calculator"


def test_tool_invocation_rejects_empty_or_invalid_tool_name():
    with pytest.raises(ValueError, match="Tool name cannot be empty"):
        ToolInvocation(tool_name="", arguments={})

    with pytest.raises(ValueError, match="Invalid tool name format"):
        ToolInvocation(tool_name="invalid tool name!", arguments={})


def test_tool_invocation_rejects_non_dict_arguments():
    with pytest.raises(ValueError, match="Arguments must be a dictionary"):
        ToolInvocation(tool_name="calculator", arguments="10 + 20")  # type: ignore


def test_calculator_expression_validation():
    # Valid mathematical expression
    inv = ToolInvocation(
        tool_name="calculator",
        arguments={"expression": "(10 + 5) * 2 / 3 - 4.5"},
    )
    assert inv.arguments["expression"] == "(10 + 5) * 2 / 3 - 4.5"

    # Missing expression key
    with pytest.raises(ValueError, match="Calculator invocation requires 'expression'"):
        ToolInvocation(tool_name="calculator", arguments={"expr": "10 + 5"})

    # Non-string expression
    with pytest.raises(ValueError, match="Calculator expression must be a string"):
        ToolInvocation(tool_name="calculator", arguments={"expression": 123})  # type: ignore

    # Unsafe / malicious injection expression
    with pytest.raises(
        ValueError, match="Calculator expression contains unsafe or invalid characters"
    ):
        ToolInvocation(
            tool_name="calculator", arguments={"expression": "__import__('os').system('ls')"}
        )


def test_tool_invocation_to_dict():
    inv = ToolInvocation(
        tool_name="time",
        arguments={},
        purpose="Get time",
        step_number=2,
    )
    d = inv.to_dict()
    assert d == {
        "tool_name": "time",
        "arguments": {},
        "purpose": "Get time",
        "step_number": 2,
    }


def test_tool_invocation_immutability():
    inv = ToolInvocation(
        tool_name="time",
        arguments={},
    )
    with pytest.raises(AttributeError):
        inv.tool_name = "calculator"  # type: ignore


def test_tool_invocation_namespaced_plugin_tools():
    """Verify valid namespaced plugin tools (plugin_id.tool_name) are accepted and normalized."""
    valid_names = [
        "my_plugin.tool_name",
        "system-diag.status_check",
        "custom_tool.v1",
        "org.vendor.plugin_tool",
        "a.b",
        "PLUGIN.TOOL",
    ]
    for name in valid_names:
        inv = ToolInvocation(tool_name=name, arguments={})
        assert inv.tool_name == name.strip().lower()


def test_tool_invocation_rejects_malformed_namespaced_names():
    """Verify malformed dot combinations, metacharacters, and arbitrary invalid tool names are rejected."""
    invalid_names = [
        ".leading_dot",
        "trailing_dot.",
        "consecutive..dots",
        "...",
        ".",
        "has space.tool",
        "tool;rm -rf",
        "tool|pipe",
        "tool/path",
        "tool\\unc",
        "tool$var",
        "tool<redirect",
        "tool>redirect",
        "tool&bg",
        "tool@name",
        "tool#name",
        "tool!name",
    ]
    for bad_name in invalid_names:
        with pytest.raises(ValueError, match="Invalid tool name format"):
            ToolInvocation(tool_name=bad_name, arguments={})
