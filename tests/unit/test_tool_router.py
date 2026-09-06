import pytest

from services.brain.tool_router import ToolRouter

def test_tool_router_detects_direct_calculation():
    router = ToolRouter()

    assert router.should_use_tool(
        "calculator",
        "10 + 20",
    )

def test_tool_router_detects_natural_language_calculation():
    router = ToolRouter()

    assert router.should_use_tool(
        "calculator",
        "What is 10 + 20?",
    )

def test_tool_router_rejects_non_calculation():
    router = ToolRouter()

    assert not router.should_use_tool(
        "calculator",
        "Hello ECHO",
    )

def test_tool_router_rejects_unknown_tool():
    router = ToolRouter()

    assert not router.should_use_tool(
        "weather",
        "What is the weather",
    )

def test_tool_router_extracts_calculation():
    router = ToolRouter()

    assert router.extract_calculation(
        "Calculate 25 * 4"
    ) == "25 * 4"

def test_tool_router_converts_power_operator():
    router = ToolRouter()

    assert router.extract_calculation(
        "2 ^ 3"
    ) == "2 ^ 3"

def test_tool_router_unknown_tool_execution():
    router = ToolRouter()

    with pytest.raises(ValueError):
        router.execute_tool(
            "unknown_tool",
            "hello",
        )

def test_tool_router_executes_registered_calculator():
    router = ToolRouter()

    result = router.execute_tool(
        "calculator",
        "25 * 4",
    )

    assert result == 100

def test_tool_router_executes_natural_language_calculator():
    router = ToolRouter()

    result = router.execute_tool(
        "calculator",
        "What is 25 * 4?",
    )

    assert result == 100

def test_tool_router_rejects_unregistered_tool():
    router = ToolRouter()

    with pytest.raises(ValueError, match="Unknown or unsupported tool"):
        router.execute_tool(
            "weather",
            "What is the weather?",
        )

def test_tool_router_detects_time_tool():
    router = ToolRouter()

    assert router.should_use_tool(
        "time",
        "What time is it?",
    )

def test_tool_router_executes_time_tool():
    router = ToolRouter()

    result = router.execute_tool("time")

    assert isinstance(result, str)
    assert len(result) == 11
    assert result[-2:] in ("AM", "PM")

def test_tool_router_detects_registered_time_tool():
    router = ToolRouter()

    assert router.should_use_tool(
        "time",
        "What time is it?",
    )

def test_tool_router_rejects_invalid_time_request():
    router = ToolRouter()

    assert not router.should_use_tool(
        "time",
        "Tell me a joke",
    )

def test_tool_router_detects_current_time_request():
    router = ToolRouter()

    assert router.should_use_tool(
        "time",
        "What is the current time?",
    )

def test_tool_router_returns_available_tools():
    router = ToolRouter()

    tools = router.get_available_tools()

    names = {
        tool["name"]
        for tool in tools
    }

    assert "calculator" in names
    assert "time" in names

def test_tool_router_detects_date_tool():
    router = ToolRouter()

    assert router.should_use_tool(
        "date",
        "What is today's date?",
    )

def test_tool_router_rejects_date_for_unrelated_message():
    router = ToolRouter()

    assert not router.should_use_tool(
        "date",
        "Hello ECHO",
    )

def test_tool_router_executes_date_tool():
    router = ToolRouter()

    result = router.execute_tool("date")

    assert isinstance(result, str)
    assert len(result) == 10
    assert result[2] == "-"
    assert result[5] == "-"

def test_tool_router_gets_available_tools():
    router = ToolRouter()

    tools = router.get_available_tools()

    assert isinstance(tools, list)

    names = [tool["name"] for tool in tools]

    assert "calculator" in names
    assert "time" in names
    assert "date" in names

def test_tool_router_executes_time_tool():
    router = ToolRouter()

    result = router.execute_tool("time")

    assert isinstance(result, str)
    assert len(result) == 11
    assert result[-2:] in ("AM", "PM")

def test_tool_router_executes_date_tool():
    router = ToolRouter()

    result = router.execute_tool("date")

    assert isinstance(result, str)
    assert len(result) == 10
    assert result[2] == "-"
    assert result[5] == "-"

def test_tool_router_detects_registered_tool():
    router = ToolRouter()

    assert router.should_use_tool(
        "calculator",
        "25 + 25",
    )

def test_tool_router_rejects_unregistered_tool():
    router = ToolRouter()

    assert not router.should_use_tool(
        "unknown_tool",
        "hello",
    )

def test_tool_router_executes_registered_tool(monkeypatch):
    router = ToolRouter()

    result = router.execute_tool(
        "calculator",
        expression="25 + 25",
    )

    assert result == 50

def test_tool_router_checks_registered_tool():
    router = ToolRouter()

    assert router.is_tool_registered("calculator")

def test_tool_router_rejects_unregistered_tool():
    router = ToolRouter()

    assert not router.is_tool_registered("unknown_tool")

def test_tool_router_maps_calculator_intent():
    router = ToolRouter()

    assert router.get_tool_for_intent(
        "calculator"
    ) == "calculator"


def test_tool_router_maps_time_intent():
    router = ToolRouter()

    assert router.get_tool_for_intent(
        "time"
    ) == "time"


def test_tool_router_maps_date_intent():
    router = ToolRouter()

    assert router.get_tool_for_intent(
        "date"
    ) == "date"


def test_tool_router_returns_none_for_unknown_intent():
    router = ToolRouter()

    assert router.get_tool_for_intent(
        "weather"
    ) is None

def test_tool_router_executes_time_for_intent():
    router = ToolRouter()

    result = router.execute_for_intent(
        "time",
        "What time is it?",
    )

    assert isinstance(result, str)
    assert len(result) == 11


def test_tool_router_executes_date_for_intent():
    router = ToolRouter()

    result = router.execute_for_intent(
        "date",
        "What is today's date?",
    )

    assert isinstance(result, str)
    assert len(result) == 10


def test_tool_router_rejects_unknown_intent():
    router = ToolRouter()

    with pytest.raises(ValueError):
        router.execute_for_intent(
            "weather",
            "What is the weather?",
        )

def test_tool_router_executes_calculator_for_intent():
    router = ToolRouter()

    result = router.execute_for_intent(
        "calculator",
        "What is 25 * 4?",
    )

    assert result == 100

def test_tool_router_rejects_invalid_calculation_for_intent():
    router = ToolRouter()

    with pytest.raises(ValueError, match="No valid calculation found"):
        router.execute_for_intent(
            "calculator",
            "Hello ECHO",
        )

def test_tool_router_extracts_calculation_with_question_mark():
    router = ToolRouter()

    assert router.extract_calculation(
        "What is 25 + 5?"
    ) == "25 + 5"


def test_tool_router_extracts_calculation_case_insensitively():
    router = ToolRouter()

    assert router.extract_calculation(
        "CALCULATE 25 * 4"
    ) == "25 * 4"


def test_tool_router_rejects_invalid_calculation():
    router = ToolRouter()

    assert router.extract_calculation(
        "What is twenty plus five?"
    ) is None


def test_tool_router_supports_power_expression():
    router = ToolRouter()

    result = router.execute_tool(
        "calculator",
        "2 ^ 3",
    )

    assert result == 8


def test_tool_router_rejects_empty_calculation():
    router = ToolRouter()

    with pytest.raises(ValueError, match="No valid calculation found"):
        router.execute_tool(
            "calculator",
            "",
        )


def test_tool_router_rejects_invalid_calculator_message():
    router = ToolRouter()

    with pytest.raises(ValueError, match="No valid calculation found"):
        router.execute_tool(
            "calculator",
            "Hello ECHO",
        )


def test_tool_router_normalizes_tool_name_lookup():
    router = ToolRouter()

    assert router.is_tool_registered("calculator")

def test_tool_router_propagates_registry_exception(monkeypatch):
    router = ToolRouter()

    def failing_execute(tool_name, **kwargs):
        raise RuntimeError("Tool registry crashed.")

    monkeypatch.setattr(
        "services.brain.tool_router.tool_registry.execute",
        failing_execute,
    )

    with pytest.raises(
        RuntimeError,
        match="Tool execution failed: Tool registry crashed.",
    ):
        router.execute_tool("time")
