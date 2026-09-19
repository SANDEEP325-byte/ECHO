"""Coding Cognition Engine (Phase 7D).

Provides deliberative coding-domain reasoning, task classification,
context extraction, structured plan synthesis, and prompt boundaries.

STRICT INVARIANTS:
1. Purely a deliberative reasoning helper — NOT an execution engine.
2. Does NOT execute tools, call subprocesses, or write files.
3. Does NOT bypass SafetyEngine, ExecutionEngine, or ToolRouter.
4. Strictly bounds all code context (< 8 KB, <= 3 files, <= 100 lines/file, <= 5 search hits).
5. Treats all repository content as untrusted data.
6. Does NOT introduce autonomous loops.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.interfaces.plan import PlanStep
from services.coding.workspace import CodingWorkspace, workspace_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class CodingSubIntent(str, Enum):
    """Specific cognitive sub-intents for coding requests."""

    EXPLORE = "explore"
    DIAGNOSE = "diagnose"
    EXPLAIN = "explain"
    PROPOSE = "propose"
    MODIFY = "modify"
    TEST = "test"


# Strict Python-enforced bounds
MAX_FILES: int = 3
MAX_LINES_PER_FILE: int = 100
MAX_SEARCH_HITS: int = 5
MAX_CONTEXT_BYTES: int = 8192
MAX_TEST_SUMMARY_LENGTH: int = 1000


@dataclass(frozen=True)
class CodeFileSlice:
    """Bounded slice of a source code file."""

    path: str
    start_line: int
    end_line: int
    content: str
    total_lines: int
    truncated: bool = False


@dataclass(frozen=True)
class SearchHit:
    """Bounded search match representation."""

    path: str
    line_number: int
    line_content: str


@dataclass
class CodingContext:
    """Structurally bounded repository context for coding deliberation."""

    workspace_root: str | None = None
    files: list[CodeFileSlice] = field(default_factory=list)
    search_hits: list[SearchHit] = field(default_factory=list)
    test_summary: str | None = None
    truncated: bool = False
    total_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary representation."""
        return {
            "workspace_root": self.workspace_root,
            "files": [
                {
                    "path": f.path,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "content": f.content,
                    "total_lines": f.total_lines,
                    "truncated": f.truncated,
                }
                for f in self.files
            ],
            "search_hits": [
                {
                    "path": h.path,
                    "line_number": h.line_number,
                    "line_content": h.line_content,
                }
                for h in self.search_hits
            ],
            "test_summary": self.test_summary,
            "truncated": self.truncated,
            "total_bytes": self.total_bytes,
        }

    def to_prompt_context(self) -> str:
        """Format bounded context string with clear untrusted boundaries."""
        parts: list[str] = []

        if self.workspace_root:
            parts.append(f"Active Workspace Root: {self.workspace_root}")

        if self.test_summary:
            parts.append(f"Recent Test Summary:\n{self.test_summary}")

        if self.search_hits:
            hit_lines = ["Recent Search Matches:"]
            for hit in self.search_hits:
                hit_lines.append(f"- {hit.path}:{hit.line_number}: {hit.line_content}")
            parts.append("\n".join(hit_lines))

        if self.files:
            file_sections = ["Source Code Slices:"]
            for f in self.files:
                trunc_note = " [truncated]" if f.truncated else ""
                file_sections.append(
                    f"--- File: {f.path} (lines {f.start_line}-{f.end_line} of {f.total_lines}){trunc_note} ---\n"
                    f"{f.content}"
                )
            parts.append("\n\n".join(file_sections))

        if self.truncated:
            parts.append("[Note: Context exceeded limits and was safely bounded/truncated]")

        raw_text = "\n\n".join(parts)
        if len(raw_text.encode("utf-8")) > MAX_CONTEXT_BYTES:
            # Hard fallback truncation if multi-component total still exceeds max bytes
            raw_bytes = raw_text.encode("utf-8")[: MAX_CONTEXT_BYTES - 100]
            raw_text = (
                raw_bytes.decode("utf-8", errors="ignore")
                + "\n... [Context truncated to maximum 8 KB limit]"
            )

        return raw_text


class CodingCognition:
    """Deliberative coding cognition engine for ECHO."""

    # General programming concept queries that should remain INFORMATIONAL, not CODING
    GENERAL_THEORY_PATTERNS = (
        r"^what\s+is\s+(a\s+|an\s+|the\s+)?(python\s+)?(class|function|method|closure|generator|decorator|lambda|recursion|tuple|list|dict|set|pointer|interface|polymorphism|inheritance|binary\s+tree|linked\s+list|stack|queue|hash\s+map|algorithm|api|rest|json)\??$",
        r"^explain\s+(the\s+)?(concept\s+of\s+)?(recursion|polymorphism|inheritance|oop|functional\s+programming|quicksort|mergesort|big\s+o|asyncio|gil)\??$",
        r"^how\s+does\s+(recursion|a\s+binary\s+search\s+tree|garbage\s+collection|the\s+gil|asyncio)\s+work(\s+in\s+general)?\??$",
        r"^difference\s+between\s+(a\s+)?(class|struct|process|thread|list|tuple)\s+and\s+(a\s+)?(class|struct|process|thread|list|tuple)\??$",
    )

    # Coding indicators for repository tasks
    FILE_EXT_PATTERN = re.compile(
        r"\b[\w\-./\\]+\.(py|js|ts|jsx|tsx|json|toml|yaml|yml|md|html|css|sql|sh|bat|ps1)\b",
        re.IGNORECASE,
    )
    TRACEBACK_PATTERN = re.compile(
        r"(Traceback\s+\(most\s+recent\s+call\s+last\)|File\s+\"[^\"]+\",\s+line\s+\d+|AssertionError|KeyError|TypeError|ValueError|ImportError|ModuleNotFoundError|AttributeError|SyntaxError)",
        re.IGNORECASE,
    )
    TEST_COMMAND_PATTERN = re.compile(
        r"\b(run\s+tests?|run\s+pytest|run\s+unittest|execute\s+tests?|test\s+runner|run\s+the\s+tests?|run\s+suite)\b",
        re.IGNORECASE,
    )
    INSPECT_TREE_PATTERN = re.compile(
        r"\b(code\s+tree|inspect\s+code\s+tree|workspace\s+tree|show\s+code\s+tree|repository\s+tree|list\s+workspace\s+files)\b",
        re.IGNORECASE,
    )
    SEARCH_CODE_PATTERN = re.compile(
        r"\b(search\s+code(\s+for)?|find\s+where\b.*(defined|implemented)|grep\s+for|find\s+references\s+to)\b",
        re.IGNORECASE,
    )

    def classify_coding_intent(
        self,
        user_input: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None, float]:
        """Determine whether the request is a repository coding task and its sub-intent.

        Returns (is_coding, sub_intent, confidence).
        Guarantees:
        - General theoretical questions fail-safe to INFORMATIONAL (is_coding=False).
        - Desktop/general file operations fail-safe to general handling.
        - Ambiguous requests fail-safe to read-only exploration or non-coding.
        """
        if not user_input or not user_input.strip():
            return False, None, 0.0

        normalized = user_input.strip().lower()

        # 1. Rule out general theoretical programming questions
        for pattern in self.GENERAL_THEORY_PATTERNS:
            if re.match(pattern, normalized) and not any(
                marker in normalized
                for marker in (
                    "in this repo",
                    "in this repository",
                    "in this codebase",
                    "in this project",
                    "in our code",
                    "here",
                )
            ):
                logger.debug("Query '{}' matched general programming theory pattern", user_input)
                return False, None, 0.95

        # 2. Direct Test Execution intent
        if self.TEST_COMMAND_PATTERN.search(normalized) or normalized.startswith("pytest"):
            return True, CodingSubIntent.TEST, 1.0

        # 3. Direct Code Tree / Workspace inspection
        if self.INSPECT_TREE_PATTERN.search(normalized):
            return True, CodingSubIntent.EXPLORE, 1.0

        # 4. Direct Code Search
        if self.SEARCH_CODE_PATTERN.search(normalized):
            return True, CodingSubIntent.EXPLORE, 0.95

        # 5. Traceback / Diagnostic failure
        if self.TRACEBACK_PATTERN.search(user_input) or any(
            marker in normalized
            for marker in (
                "why is this failing",
                "why did this fail",
                "why is this function failing",
                "why is the test failing",
                "explain this error",
                "diagnose this error",
                "what caused this error",
                "find the bug in",
                "why is there a syntax error",
            )
        ):
            return True, CodingSubIntent.DIAGNOSE, 0.95

        # 6. Proposal (read-only fix suggestion)
        if any(
            marker in normalized
            for marker in (
                "how should i fix",
                "how to fix this",
                "propose a fix",
                "suggest a solution for",
                "recommend changes for",
                "how can i solve this bug",
            )
        ):
            return True, CodingSubIntent.PROPOSE, 0.9

        # 7. Concrete Modification intent
        if any(
            marker in normalized
            for marker in (
                "modify this function",
                "modify the function",
                "change this function",
                "replace block in",
                "apply patch",
                "fix the bug in this function",
                "refactor this function",
                "update file",
                "edit file",
                "add a method to",
            )
        ):
            return True, CodingSubIntent.MODIFY, 0.95

        # 8. Explanation intent targeting repository code
        if any(
            marker in normalized
            for marker in (
                "explain this code",
                "explain this function",
                "explain this class",
                "explain this file",
                "how does this module work",
                "walk me through",
            )
        ) or (self.FILE_EXT_PATTERN.search(normalized) and "explain" in normalized):
            return True, CodingSubIntent.EXPLAIN, 0.9

        # 9. General file/path references or symbol lookup within workspace
        has_file_ref = bool(self.FILE_EXT_PATTERN.search(user_input))
        has_repo_ref = any(
            marker in normalized
            for marker in (
                "in this repo",
                "in this repository",
                "in the codebase",
                "in this project",
                "in services/",
                "in packages/",
                "in tests/",
            )
        )

        if has_file_ref and (
            has_repo_ref
            or any(
                v in normalized
                for v in (
                    "read",
                    "inspect",
                    "show",
                    "view",
                    "check",
                    "open",
                    "find",
                    "where is",
                )
            )
        ):
            return True, CodingSubIntent.EXPLORE, 0.85

        if has_repo_ref and any(
            v in normalized for v in ("where is", "find", "locate", "which file")
        ):
            return True, CodingSubIntent.EXPLORE, 0.85

        # Ambiguous queries fail safe to non-coding
        return False, None, 0.0

    def get_tools_for_sub_intent(self, sub_intent: str | None) -> list[str]:
        """Return the minimal necessary tools for a coding sub-intent."""
        if sub_intent == CodingSubIntent.TEST:
            return ["run_tests"]
        if sub_intent == CodingSubIntent.EXPLORE:
            return ["inspect_code_tree", "search_code", "read_code"]
        if sub_intent in {
            CodingSubIntent.DIAGNOSE,
            CodingSubIntent.EXPLAIN,
            CodingSubIntent.PROPOSE,
        }:
            # Strictly read-only tools
            return ["read_code", "search_code"]
        if sub_intent == CodingSubIntent.MODIFY:
            # Modification flow includes read, modify, patch, and test
            return ["read_code", "modify_code", "apply_patch", "run_tests"]
        return ["read_code", "search_code"]

    def extract_coding_context(
        self,
        request_or_input: Any,
        workspace: CodingWorkspace | None = None,
        files_to_read: list[dict[str, Any]] | None = None,
        search_results: list[dict[str, Any]] | None = None,
        test_summary: str | None = None,
    ) -> CodingContext:
        """Extract and assemble a structurally bounded CodingContext.

        Strictly enforces:
        - <= 3 files
        - <= 100 lines/file
        - <= 5 search hits
        - <= 8 KB total context payload
        """
        active_ws = workspace or workspace_manager
        root_path = str(active_ws.root) if active_ws else None

        context = CodingContext(
            workspace_root=root_path,
            files=[],
            search_hits=[],
            test_summary=None,
            truncated=False,
            total_bytes=0,
        )

        total_bytes = len(root_path.encode("utf-8")) if root_path else 0

        # 1. Bounded Test Summary
        if test_summary:
            clean_summary = test_summary.strip()
            if len(clean_summary) > MAX_TEST_SUMMARY_LENGTH:
                clean_summary = clean_summary[:MAX_TEST_SUMMARY_LENGTH] + "... [summary truncated]"
                context.truncated = True
            context.test_summary = clean_summary
            total_bytes += len(clean_summary.encode("utf-8"))

        # 2. Bounded Search Hits (max 5)
        if search_results:
            raw_hits = search_results[:MAX_SEARCH_HITS]
            if len(search_results) > MAX_SEARCH_HITS:
                context.truncated = True

            for hit in raw_hits:
                path_str = str(hit.get("file_path") or hit.get("path") or "")
                line_no = int(hit.get("line_number") or 1)
                line_content = str(hit.get("line_content") or hit.get("content") or "")[:200]
                hit_bytes = len(path_str.encode("utf-8")) + len(line_content.encode("utf-8")) + 30

                if total_bytes + hit_bytes > MAX_CONTEXT_BYTES:
                    context.truncated = True
                    break

                context.search_hits.append(
                    SearchHit(
                        path=path_str,
                        line_number=line_no,
                        line_content=line_content,
                    )
                )
                total_bytes += hit_bytes

        # 3. Bounded Files (max 3 files, max 100 lines each)
        if files_to_read:
            raw_files = files_to_read[:MAX_FILES]
            if len(files_to_read) > MAX_FILES:
                context.truncated = True

            for f_info in raw_files:
                path_str = str(f_info.get("path") or f_info.get("file_path") or "")
                raw_content = str(f_info.get("content") or "")
                start_l = int(f_info.get("start_line") or 1)

                lines = raw_content.splitlines()
                total_lines = len(lines)
                f_truncated = False

                if len(lines) > MAX_LINES_PER_FILE:
                    lines = lines[:MAX_LINES_PER_FILE]
                    f_truncated = True
                    context.truncated = True

                bounded_content = "\n".join(lines)
                file_bytes = (
                    len(path_str.encode("utf-8")) + len(bounded_content.encode("utf-8")) + 100
                )

                if total_bytes + file_bytes > MAX_CONTEXT_BYTES:
                    # Truncate content further to fit byte budget
                    remaining_budget = max(0, MAX_CONTEXT_BYTES - total_bytes - 150)
                    if remaining_budget > 100:
                        bounded_content = (
                            bounded_content.encode("utf-8")[:remaining_budget].decode(
                                "utf-8", errors="ignore"
                            )
                            + "\n... [truncated to fit 8 KB budget]"
                        )
                        f_truncated = True
                        context.truncated = True
                        file_bytes = len(bounded_content.encode("utf-8")) + 100
                    else:
                        context.truncated = True
                        break

                context.files.append(
                    CodeFileSlice(
                        path=path_str,
                        start_line=start_l,
                        end_line=start_l + len(lines) - 1,
                        content=bounded_content,
                        total_lines=total_lines,
                        truncated=f_truncated,
                    )
                )
                total_bytes += file_bytes

        context.total_bytes = total_bytes
        return context

    def build_coding_plan(
        self,
        user_input: str,
        sub_intent: str | None = None,
        extracted_params: dict[str, Any] | None = None,
    ) -> list[PlanStep]:
        """Synthesize a structured execution plan for a coding task.

        Workflows:
        - EXPLORE: search/tree -> read -> synthesize (read-only)
        - DIAGNOSE: read -> analyze error -> explain (read-only)
        - EXPLAIN: read -> explain structure (read-only)
        - PROPOSE: read -> synthesize proposed patch (read-only, no write tool)
        - MODIFY: read -> modify_code (SENSITIVE: confirmation required) -> run_tests (SENSITIVE) -> verify
        - TEST: run_tests (SENSITIVE: confirmation required) -> verify
        """
        params = extracted_params or {}
        normalized = user_input.strip().lower()

        # Resolve sub-intent if not explicitly passed
        if not sub_intent:
            _, resolved_sub_intent, _ = self.classify_coding_intent(user_input)
            sub_intent = resolved_sub_intent or CodingSubIntent.EXPLORE

        # Extract target file or symbol hints from query if available
        file_match = self.FILE_EXT_PATTERN.search(user_input)
        target_path = params.get("file_path") or (file_match.group(0) if file_match else None)

        # 1. TEST WORKFLOW
        if sub_intent == CodingSubIntent.TEST:
            framework = params.get("framework", "pytest")
            test_targets = [target_path] if target_path else []
            return [
                PlanStep(
                    step_number=1,
                    description=f"Execute {framework} test suite on authorized workspace.",
                    tool_name="run_tests",
                    arguments={"framework": framework, "targets": test_targets},
                    purpose="Run targeted test verification",
                ),
                PlanStep(
                    step_number=2,
                    description="Verify test execution results and report pass/fail summary.",
                    purpose="Evaluate test verification postcondition",
                ),
            ]

        # 2. EXPLORATION WORKFLOW
        if sub_intent == CodingSubIntent.EXPLORE:
            if self.INSPECT_TREE_PATTERN.search(normalized):
                return [
                    PlanStep(
                        step_number=1,
                        description="Inspect workspace directory structure.",
                        tool_name="inspect_code_tree",
                        arguments={"max_depth": 3, "max_files": 100},
                        purpose="Survey repository structure",
                    ),
                    PlanStep(
                        step_number=2,
                        description="Synthesize code tree summary for user inquiry.",
                        purpose="Explain repository layout",
                    ),
                ]

            if target_path:
                return [
                    PlanStep(
                        step_number=1,
                        description=f"Read contents of '{target_path}'.",
                        tool_name="read_code",
                        arguments={"file_path": target_path, "start_line": 1, "end_line": 100},
                        purpose="Inspect target file content",
                    ),
                    PlanStep(
                        step_number=2,
                        description="Synthesize file explanation and details.",
                        purpose="Answer inquiry about target file",
                    ),
                ]

            # Search query exploration
            search_query = params.get("query") or self._extract_search_term(user_input)
            return [
                PlanStep(
                    step_number=1,
                    description=f"Search workspace for '{search_query}'.",
                    tool_name="search_code",
                    arguments={"query": search_query, "max_matches": 20},
                    purpose="Locate symbol or implementation in workspace",
                ),
                PlanStep(
                    step_number=2,
                    description="Read target file at matching location.",
                    tool_name="read_code",
                    arguments={},
                    purpose="Inspect located code lines",
                ),
                PlanStep(
                    step_number=3,
                    description="Explain located code and answer inquiry.",
                    purpose="Synthesize search results",
                ),
            ]

        # 3. DIAGNOSIS WORKFLOW (strictly read-only)
        if sub_intent == CodingSubIntent.DIAGNOSE:
            return [
                PlanStep(
                    step_number=1,
                    description=f"Inspect code context for '{target_path or 'failing module'}'.",
                    tool_name="read_code" if target_path else "search_code",
                    arguments={"file_path": target_path} if target_path else {"query": "error"},
                    purpose="Gather code context around error",
                ),
                PlanStep(
                    step_number=2,
                    description="Analyze root cause and diagnose bug.",
                    purpose="Explain failure mechanism to user",
                ),
            ]

        # 4. EXPLAIN WORKFLOW (strictly read-only)
        if sub_intent == CodingSubIntent.EXPLAIN:
            return [
                PlanStep(
                    step_number=1,
                    description=f"Read target source code for '{target_path or 'requested component'}'.",
                    tool_name="read_code" if target_path else "search_code",
                    arguments={"file_path": target_path} if target_path else {"query": "class"},
                    purpose="Read code for explanation",
                ),
                PlanStep(
                    step_number=2,
                    description="Synthesize architectural and functional explanation of the code.",
                    purpose="Explain code structure and logic",
                ),
            ]

        # 5. PROPOSAL WORKFLOW (strictly read-only)
        if sub_intent == CodingSubIntent.PROPOSE:
            return [
                PlanStep(
                    step_number=1,
                    description=f"Read current code block in '{target_path or 'target file'}'.",
                    tool_name="read_code" if target_path else "search_code",
                    arguments={"file_path": target_path} if target_path else {"query": "def"},
                    purpose="Establish baseline code before proposing changes",
                ),
                PlanStep(
                    step_number=2,
                    description="Generate proposed code diff and explanation for user review.",
                    purpose="Propose solution without performing file modifications",
                ),
            ]

        # 6. CONTROLLED MODIFICATION WORKFLOW
        # Step 2 (modify_code) and Step 3 (run_tests) are classified as SENSITIVE in RiskClassifier.
        # ExecutionEngine will pause at step 2, generate a PendingAction, and request user confirmation.
        return [
            PlanStep(
                step_number=1,
                description=f"Read target file '{target_path or 'target'}' to confirm existing code block.",
                tool_name="read_code" if target_path else "search_code",
                arguments={"file_path": target_path} if target_path else {"query": "def"},
                purpose="Ground modification against actual repository code",
            ),
            PlanStep(
                step_number=2,
                description=f"Apply targeted modification to '{target_path or 'target'}'.",
                tool_name="modify_code",
                arguments={"file_path": target_path} if target_path else {},
                purpose="Apply validated code edit (Requires User Confirmation)",
            ),
            PlanStep(
                step_number=3,
                description="Run regression tests to verify modification.",
                tool_name="run_tests",
                arguments={"framework": "pytest"},
                purpose="Verify changes with test execution (Requires User Confirmation)",
            ),
            PlanStep(
                step_number=4,
                description="Verify postconditions of modification and test run.",
                purpose="Verify overall task completion",
            ),
        ]

    @staticmethod
    def _extract_search_term(user_input: str) -> str:
        """Helper to extract search keywords from free-form user query."""
        cleaned = re.sub(
            r"^(find\s+where|search\s+for|search\s+code\s+for|where\s+is|locate|show\s+me)\s+",
            "",
            user_input.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+(is\s+implemented|is\s+defined|is\s+located|in\s+this\s+repo.*)$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.strip("\"' ")
        return cleaned or "main"


coding_cognition = CodingCognition()
