from services.brain.tools.calculator import CalculatorTool
import pytest

def test_calculator_tool_adds_numbers():
    calculator = CalculatorTool()

    result = calculator.execute("10 + 20")

    assert result == 30
    
def test_calculator_tool_evaluates_multiple_operators():
    calculator = CalculatorTool()

    result = calculator.execute("10 + 5 * 2")

    assert result == 20
    
def test_calculator_tool_respects_parentheses():
    calculator = CalculatorTool()

    result = calculator.execute("(10 + 5) * 2")

    assert result == 30

def test_calculator_tool_rejects_invalid_expression():
    calculator = CalculatorTool()

    with pytest.raises(ValueError, match="Invalid mathematical expression"):
        calculator.execute("10 + abc")
        
def test_calculator_tool_rejects_function_calls():
    calculator = CalculatorTool()

    with pytest.raises(ValueError, match="Invalid mathematical expression"):
        calculator.execute("__import__('os').system('echo hacked')")
        
def test_calculator_tool_handles_negative_numbers():
    calculator = CalculatorTool()

    result = calculator.execute("-10 + 5")

    assert result == -5
    
def test_calculator_tool_divides_numbers():
    calculator = CalculatorTool()

    result = calculator.execute("20 / 4")

    assert result == 5.0
    
def test_calculator_tool_calculates_modulo():
    calculator = CalculatorTool()

    result = calculator.execute("17 % 5")

    assert result == 2
    
def test_calculator_tool_calculates_power():
    calculator = CalculatorTool()

    result = calculator.execute("2 ** 3")

    assert result == 8
    
def test_calculator_tool_rejects_unsupported_operator():
    calculator = CalculatorTool()
    
    with pytest.raises(ValueError, match="Unsupported operator"):
        calculator.execute("10 // 3")
        
def test_calculator_tool_rejects_division_by_zero():
    calculator = CalculatorTool()

    with pytest.raises(ZeroDivisionError):
        calculator.execute("10 / 0")
        
def test_calculator_tool_rejects_invalid_syntax():
    calculator = CalculatorTool()
    
    with pytest.raises(SyntaxError):
        calculator.execute("10 +")
        
def test_calculator_tool_handles_decimal_numbers():
    calculator = CalculatorTool()
    
    result = calculator.execute("10.5 + 2.5")
    
    assert result == 13.0
    
def test_calculator_tool_handles_negative_right_operand():
    calculator = CalculatorTool()

    result = calculator.execute("10 + -5")

    assert result == 5