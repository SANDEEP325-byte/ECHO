from packages.interfaces.tool_result import ToolResult


def test_tool_result_success():
    result = ToolResult(
        tool_name="calculator",
        success=True,
        result=100,
    )

    assert result.tool_name == "calculator"
    assert result.success is True
    assert result.result == 100
    assert result.error is None


def test_tool_result_failure():
    result = ToolResult(
        tool_name="calculator",
        success=False,
        error="Invalid expression.",
    )

    assert result.tool_name == "calculator"
    assert result.success is False
    assert result.result is None
    assert result.error == "Invalid expression."
    
def test_tool_result_rejects_empty_tool_name():
    try:
        ToolResult(
            tool_name="",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_result_rejects_non_boolean_success():
    try:
        ToolResult(
            tool_name="calculator",
            success="yes",
        )
        assert False
    except TypeError:
        pass