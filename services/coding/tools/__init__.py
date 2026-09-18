"""ECHO Coding Tools (Phase 7A & 7B).

Exposes inspection tools:
- inspect_code_tree
- search_code
- read_code

Exposes modification tools:
- modify_code
- apply_patch
"""

from services.coding.tools.code_edit import ModifyCodeTool, modify_code_tool
from services.coding.tools.code_patch import ApplyPatchTool, apply_patch_tool
from services.coding.tools.code_read import ReadCodeTool, read_code_tool
from services.coding.tools.code_search import SearchCodeTool, search_code_tool
from services.coding.tools.code_tree import InspectCodeTreeTool, inspect_code_tree_tool

ALL_CODING_TOOLS = (
    inspect_code_tree_tool,
    search_code_tool,
    read_code_tool,
    modify_code_tool,
    apply_patch_tool,
)

__all__ = [
    "ALL_CODING_TOOLS",
    "ApplyPatchTool",
    "InspectCodeTreeTool",
    "ModifyCodeTool",
    "ReadCodeTool",
    "SearchCodeTool",
    "apply_patch_tool",
    "inspect_code_tree_tool",
    "modify_code_tool",
    "read_code_tool",
    "search_code_tool",
]
