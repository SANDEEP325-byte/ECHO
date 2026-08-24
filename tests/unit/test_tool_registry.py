import pytest

from packages.common.tool_registry import ToolRegistry
from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import (
    ToolDefinition,
    ToolParameter,
)


class FakeTool(Tool):
    def __init__(self, name="fake_tool"):
        self.name = name
        self.description = "A fake tool for testing."

        self.definition = ToolDefinition(
            name=name,
            description="A fake tool for testing.",
            parameters=(
                ToolParameter(
                    name="value",
                    type="string",
                    description="Value to process.",
                    required=True,
                ),
            ),
        )

    def execute(self, value: str) -> str:
        return f"processed: {value}"
    
def test_registry_registers_and_gets_tool():
    registry = ToolRegistry()
    tool = FakeTool()
    
    registry.register(tool)
    
    assert registry.get("fake_tool") is tool
        
def test_registry_returns_none_for_unknown_tool():
    registry = ToolRegistry()
    registry.register(FakeTool())
    
    result = registry.get("unknown") is None
    
def test_registry_executes_registered_tool():
    registry = ToolRegistry()
    registry.register(FakeTool())

    result = registry.execute(
        "fake_tool",
        value="hello",
    )

    assert result.success is True
    assert result.tool_name == "fake_tool"
    assert result.result == "processed: hello"
    assert result.error is None
    
def test_registry_returns_failed_result_for_unknown_tool():
    registry = ToolRegistry()

    result = registry.execute(
        "unknown",
        value="hello",
    )

    assert result.success is False
    assert result.tool_name == "unknown"
    assert result.result is None
    assert result.error == "Unknown tool: unknown"
        
def test_registry_lists_tool_definition():
    registry = ToolRegistry()
    registry.register(FakeTool())
    
    tools = registry.list_tools()
    
    assert len(tools) == 1
    assert tools[0]["name"] == "fake_tool"
    assert tools[0]["description"] == "A fake tool for testing."
    assert tools[0]["parameters"][0]["name"] == "value"
    assert tools[0]["parameters"][0]["type"] == "string"
    assert tools[0]["parameters"][0]["required"] is True
    
def test_registry_replaces_tool_with_same_name():
    registry = ToolRegistry()
    
    first_tool = FakeTool()
    second_tool = FakeTool()
    
    registry.register(first_tool)
    registry.register(second_tool)
    
    assert registry.get("fake_tool") is second_tool
    assert len(registry.list_tools()) == 1
    
def test_calculator_is_registered():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools
    
    calculator = tool_registry.get("calculator")
    
    assert calculator is not None
    assert calculator.name == "calculator"
    assert calculator.description == (
        "Performs basic arithmetic calculations."
    )
    
def test_registered_calculator_executes():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    result = tool_registry.execute(
        "calculator",
        expression="25 * 4",
    )

    assert result.success is True
    assert result.tool_name == "calculator"
    assert result.result == 100
    assert result.error is None
    
def test_registry_contains_calculator():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    calculator = tool_registry.get("calculator")

    assert calculator is not None
    assert calculator.name == "calculator"
    
def test_registry_contains_time_tool():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    time_tool = tool_registry.get("time")

    assert time_tool is not None
    assert time_tool.name == "time"


def test_registry_lists_time_tool():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    tools_list = tool_registry.list_tools()

    names = [tool["name"] for tool in tools_list]

    assert "calculator" in names
    assert "time" in names
    assert "date" in names
    
def test_registry_contains_registered_tools():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    tools_list = tool_registry.list_tools()

    names = {
        tool["name"]
        for tool in tools_list
    }

    assert "calculator" in names
    assert "time" in names
    assert "date" in names
    
def test_registry_returns_tool_definitions():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    definitions = tool_registry.get_definitions()

    names = {
        definition["name"]
        for definition in definitions
    }

    assert "calculator" in names
    assert "time" in names
    assert "date" in names
    
def test_calculator_definition_contains_expression_parameter():
    from packages.common.tool_registry import tool_registry
    from services.brain import tools

    definitions = tool_registry.get_definitions()

    calculator = next(
        definition
        for definition in definitions
        if definition["name"] == "calculator"
    )

    assert calculator["description"]
    assert calculator["parameters"]

    parameter_names = {
        parameter["name"]
        for parameter in calculator["parameters"]
    }

    assert "expression" in parameter_names
    
def test_registry_replaces_tool_with_same_name():
    from packages.common.tool_registry import ToolRegistry

    registry = ToolRegistry()

    from services.brain.tools.calculator import CalculatorTool

    first = CalculatorTool()
    second = CalculatorTool()

    registry.register(first)
    registry.register(second)

    assert registry.get("calculator") is second
    assert len(registry.list_tools()) == 1
    
def test_tool_registry_lists_registered_tools():
    registry = ToolRegistry()

    registry.register(FakeTool())

    tools = registry.list_tools()

    names = [tool["name"] for tool in tools]

    assert "fake_tool" in names


def test_tool_registry_returns_tool_definition():
    registry = ToolRegistry()

    registry.register(FakeTool())

    tools = registry.list_tools()

    fake_tool = next(
        item
        for item in tools
        if item["name"] == "fake_tool"
    )

    assert fake_tool["name"] == "fake_tool"
    assert fake_tool["description"] == "A fake tool for testing."
    assert fake_tool["parameters"][0]["name"] == "value"
    
def test_tool_registry_get_returns_registered_tool():
    registry = ToolRegistry()

    tool = FakeTool()
    registry.register(tool)

    result = registry.get("fake_tool")

    assert result is tool


def test_tool_registry_get_returns_none_for_unknown_tool():
    registry = ToolRegistry()

    assert registry.get("unknown_tool") is None
    
def test_tool_registry_executes_registered_tool():
    registry = ToolRegistry()

    tool = FakeTool("test_tool")
    registry.register(tool)

    result = registry.execute(
        "test_tool",
        value="hello",
    )

    assert result.success is True
    assert result.tool_name == "test_tool"
    assert result.result == "processed: hello"


def test_tool_registry_passes_multiple_arguments():
    registry = ToolRegistry()

    tool = FakeTool("test_tool")
    registry.register(tool)

    result = registry.execute(
        "test_tool",
        value="echo",
    )

    assert result.success is True
    assert result.tool_name == "test_tool"
    assert result.result == "processed: echo"


def test_tool_registry_execute_unknown_tool_returns_failed_result():
    registry = ToolRegistry()

    result = registry.execute(
        "does_not_exist",
        value="hello",
    )

    assert result.success is False
    assert result.tool_name == "does_not_exist"
    assert result.result is None
    assert result.error == "Unknown tool: does_not_exist"
        
def test_tool_registry_is_empty_before_tools_are_registered():
    registry = ToolRegistry()

    assert registry.list_tools() == []
    
def test_tool_registry_contains_registered_tool_definition():
    registry = ToolRegistry()

    tool = FakeTool("calculator")
    registry.register(tool)

    definitions = registry.list_tools()

    assert len(definitions) == 1
    assert definitions[0]["name"] == "calculator"
    assert definitions[0]["description"] == "A fake tool for testing."
    
def test_builtin_tools_are_registered():
    from services.brain.tools import register_builtin_tools
    from packages.common.tool_registry import tool_registry
    
    register_builtin_tools()

    definitions = tool_registry.list_tools()

    names = {
        definition["name"]
        for definition in definitions
    }

    assert {"calculator", "time", "date"} <= names
    
from packages.interfaces.tool_result import ToolResult

def test_tool_result_stores_successful_result():
    result = ToolResult(
        tool_name="calculator",
        result=100,
    )

    assert result.tool_name == "calculator"
    assert result.result == 100
    assert result.success is True


def test_tool_result_can_store_failed_result():
    result = ToolResult(
        tool_name="calculator",
        result="Invalid expression",
        success=False,
    )

    assert result.tool_name == "calculator"
    assert result.result == "Invalid expression"
    assert result.success is False
    
def test_tool_registry_execute_returns_successful_tool_result():
    registry = ToolRegistry()

    registry.register(FakeTool())

    result = registry.execute(
        "fake_tool",
        value="hello",
    )

    assert result.success is True
    assert result.tool_name == "fake_tool"
    assert result.result == "processed: hello"
    assert result.error is None


def test_tool_registry_execute_returns_failed_tool_result():
    registry = ToolRegistry()

    result = registry.execute(
        "unknown_tool",
    )

    assert result.success is False
    assert result.tool_name == "unknown_tool"
    assert result.result is None
    assert result.error == "Unknown tool: unknown_tool"