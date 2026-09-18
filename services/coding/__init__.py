"""ECHO Coding Capability Module (Phase 7).

Provides safe, deterministic, local-first workspace inspection and
controlled code modification with unified diff generation, AST syntax
pre-validation, and integration with the ECHO safety architecture.
"""

from services.coding.diff_engine import (
    DiffEngine,
    PatchHunk,
    SyntaxValidationResult,
    diff_engine,
)
from services.coding.tools import ALL_CODING_TOOLS
from services.coding.workspace import (
    CodingWorkspace,
    GitIgnoreMatcher,
    WorkspaceError,
    workspace_manager,
)

__all__ = [
    "ALL_CODING_TOOLS",
    "CodingWorkspace",
    "DiffEngine",
    "GitIgnoreMatcher",
    "PatchHunk",
    "SyntaxValidationResult",
    "WorkspaceError",
    "diff_engine",
    "workspace_manager",
]
