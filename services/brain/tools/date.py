from datetime import datetime

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import (ToolDefinition,)

class DateTool(Tool):
    name = "date"
    description = "Returns the current date."
    
    definition = ToolDefinition(
        name="date",
        description="Returns the current date.",
    )
    
    def execute(self) -> str:
        return datetime.now().strftime("%d-%m-%Y")
    
date_tool = DateTool()