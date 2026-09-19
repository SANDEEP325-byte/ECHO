"""ECHO Test Runner Tool (Phase 7C).

Provides controlled test execution for pytest and unittest inside the
authorized CodingWorkspace. Enforces positive argument allowlisting,
conservative filter expressions, strict timeouts, bounded output, and
structured test result parsing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.coding.test_runner import (
    TestPolicyError,
    test_runner,
)
from services.coding.workspace import WorkspaceError
from services.logging.logger import logger  # type: ignore[attr-defined]


class RunTestsTool(Tool):
    """Tool to execute controlled tests within the authorized coding workspace."""

    name = "run_tests"
    description = (
        "Executes controlled tests (pytest or unittest) within the authorized coding workspace. "
        "Enforces positive argument allowlisting, safe filter expressions, strict timeouts, "
        "and bounded structured test result extraction."
    )

    definition = ToolDefinition(
        name="run_tests",
        description="Executes controlled tests (pytest or unittest) within the authorized coding workspace.",
        parameters=(
            ToolParameter(
                name="framework",
                type="string",
                description="Test framework to use ('pytest' [default] or 'unittest').",
                required=False,
            ),
            ToolParameter(
                name="targets",
                type="array",
                description="Optional list of test files, directories, or node selectors to test.",
                required=False,
            ),
            ToolParameter(
                name="options",
                type="array",
                description="Optional list of allowlisted options (-v, -q, -x, -k <expr>, -m <marker>, --tb=<style>).",
                required=False,
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Maximum execution time in seconds (default: 30.0, max: 60.0).",
                required=False,
            ),
        ),
    )

    def execute(
        self,
        framework: str = "pytest",
        targets: Sequence[str] | str | None = None,
        options: Sequence[str] | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute controlled tests within the authorized workspace."""
        try:
            result = test_runner.run_tests(
                framework=framework,
                targets=targets,
                options=options,
                timeout=timeout,
            )
            return result.to_dict()
        except TestPolicyError as exc:
            return {
                "operation": "run_tests",
                "success": False,
                "error": f"Test policy violation: {exc.reason}",
                "status": "error",
                "framework": framework,
            }
        except WorkspaceError as exc:
            return {
                "operation": "run_tests",
                "success": False,
                "error": f"Workspace security violation: {exc.reason}",
                "status": "error",
                "framework": framework,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Test execution failed: %s", exc)
            return {
                "operation": "run_tests",
                "success": False,
                "error": f"Test execution failed: {exc}",
                "status": "error",
                "framework": framework,
            }


run_tests_tool = RunTestsTool()
