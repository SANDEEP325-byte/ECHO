import ast
import operator
from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import (ToolDefinition, ToolParameter,)


class CalculatorTool(Tool):
    name = "calculator"
    description = "Performs basic arithmetic calculations."

    definition = ToolDefinition(
        name="calculator",
        description="Performs basic arithmetic calculations.",
        parameters=(
            ToolParameter(
                name="expression",
                type="string",
                description="A mathematical expression to calculate.",
                required=True,
            ),
        ),
    )
    
    _operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    
    def execute(self, expression: str) -> float | int:
        tree = ast.parse(expression, mode="eval")
        
        return self._evaluate(tree.body)
    
    def _evaluate(self, node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and isinstance(
            node.value, (int, float)
        ):
            return node.value
        
        if isinstance(node, ast.BinOp):
            operation = self._operators.get(type(node.op))
            
            if operation is None:
                raise ValueError("Unsupported operator.")
            
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            
            return operation(left, right)
        
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return self._evaluate(node.operand)
            
        raise ValueError("Invalid mathematical expression.")
    
calculator_tool = CalculatorTool()