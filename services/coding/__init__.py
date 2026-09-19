"""ECHO Coding Capability Module (Phase 7).

Provides safe, deterministic, local-first workspace inspection and
controlled code modification with unified diff generation, AST syntax
pre-validation, and integration with the ECHO safety architecture.
"""

from services.coding.cognition import (
    CodeFileSlice,
    CodingCognition,
    CodingContext,
    CodingSubIntent,
    SearchHit,
    coding_cognition,
)
from services.coding.diff_engine import (
    DiffEngine,
    PatchHunk,
    SyntaxValidationResult,
    diff_engine,
)
from services.coding.test_runner import (
    TestFramework,
    TestPolicyError,
    TestResult,
    TestRunner,
    TestSummary,
    test_runner,
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
    "CodeFileSlice",
    "CodingCognition",
    "CodingContext",
    "CodingSubIntent",
    "CodingWorkspace",
    "DiffEngine",
    "GitIgnoreMatcher",
    "PatchHunk",
    "SearchHit",
    "SyntaxValidationResult",
    "TestFramework",
    "TestPolicyError",
    "TestResult",
    "TestRunner",
    "TestSummary",
    "WorkspaceError",
    "coding_cognition",
    "diff_engine",
    "test_runner",
    "workspace_manager",
]
