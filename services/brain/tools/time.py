from datetime import datetime
from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import (
    ToolDefinition,
)

class TimeTool(Tool):
    name = "time"
    description = "Returns the current local time."
    
    definition = ToolDefinition(
        name= "time",
        description= "Returns the current local time.",
    )
    
    def execute(self) -> str:
        return datetime.now().astimezone().strftime("%I:%M:%S %p")
    
time_tool = TimeTool()