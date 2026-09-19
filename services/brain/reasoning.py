from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from packages.interfaces.request import Request
from services.logging.logger import logger


class TaskType(str, Enum):
    """Categorizes the cognitive nature of a user request."""

    CONVERSATIONAL = "conversational"
    INFORMATIONAL = "informational"
    MEMORY = "memory"
    SINGLE_TOOL = "single_tool"
    MULTI_STEP = "multi_step"
    CODING = "coding"


@dataclass(frozen=True)
class ReasoningDecision:
    """Structured decision data produced by the Reasoning Engine."""

    task_type: TaskType
    requires_planning: bool = False
    tools_needed: list[str] = field(default_factory=list)
    confidence: float = 1.0
    deterministic_response: str | None = None
    intent: str = "general"
    requires_tool: bool = False
    selected_capabilities: list[str] = field(default_factory=list)
    needs_confirmation: bool = False
    coding_sub_intent: str | None = None



class ReasoningEngine:
    """Cognitive deliberation component that determines task classification and plan requirements."""

    def reason(
        self,
        user_input_or_request: str | Request,
        context: dict[str, Any] | None = None,
    ) -> ReasoningDecision:
        """Fast deliberation determining task type, tools required, and planning needs."""
        if isinstance(user_input_or_request, Request):
            user_input = user_input_or_request.user_input or ""
            intent = user_input_or_request.intent or ""
            complexity = user_input_or_request.complexity or "simple"
        else:
            user_input = str(user_input_or_request or "")
            intent = ""
            complexity = "simple"

        normalized = user_input.strip().lower()

        # 1. Greetings & Identity
        if (
            intent == "greeting"
            or normalized in {"hi", "hello", "hey", "hello echo", "hi echo", "hey echo"}
            or normalized.startswith("hello ")
            or normalized.startswith("hi ")
        ):
            return ReasoningDecision(
                task_type=TaskType.CONVERSATIONAL,
                requires_planning=False,
                confidence=1.0,
                deterministic_response="Hello! I'm ECHO, your personal AI assistant. How can I help you today? 😊",
                intent="greeting",
            )

        if (
            intent == "identity"
            or "who are you" in normalized
            or "what are you" in normalized
        ):
            return ReasoningDecision(
                task_type=TaskType.CONVERSATIONAL,
                requires_planning=False,
                confidence=1.0,
                deterministic_response="I'm ECHO, your personal AI assistant. 😌",
                intent="identity",
            )

        # 2. Memory Operations
        if (
            intent in {"memory_save", "memory_recall", "memory_delete"}
            or any(
                p in normalized
                for p in (
                    "my name is",
                    "call me",
                    "favorite color is",
                    "what is my name",
                    "what's my name",
                    "tell me what you remember",
                    "what do you remember",
                    "forget my",
                    "forget everything",
                )
            )
        ):
            return ReasoningDecision(
                task_type=TaskType.MEMORY,
                requires_planning=False,
                confidence=1.0,
                intent="memory",
            )

        # 3. Deterministic Single Tool
        if intent == "calculator" or normalized.startswith("calculate ") or re.search(r"\bcalculate\b", normalized):
            return ReasoningDecision(
                task_type=TaskType.SINGLE_TOOL,
                requires_planning=False,
                tools_needed=["calculator"],
                selected_capabilities=["calculator"],
                requires_tool=True,
                confidence=1.0,
                intent="calculator",
            )

        if intent == "time" or "what time" in normalized or "current time" in normalized:
            return ReasoningDecision(
                task_type=TaskType.SINGLE_TOOL,
                requires_planning=False,
                tools_needed=["time"],
                selected_capabilities=["time"],
                requires_tool=True,
                confidence=1.0,
                intent="time",
            )

        if intent == "date" or "what date" in normalized or "today's date" in normalized or "current date" in normalized:
            return ReasoningDecision(
                task_type=TaskType.SINGLE_TOOL,
                requires_planning=False,
                tools_needed=["date"],
                selected_capabilities=["date"],
                requires_tool=True,
                confidence=1.0,
                intent="date",
            )

        # 4. Explicit Multi-Step Workflow Orchestration
        if any(
            marker in normalized
            for marker in (
                "step by step",
                "create and run",
                "build and run",
                "then run",
                "deploy it",
                "multiple steps",
                "install and start",
            )
        ):
            return ReasoningDecision(
                task_type=TaskType.MULTI_STEP,
                requires_planning=True,
                tools_needed=["terminal"],
                selected_capabilities=["terminal"],
                requires_tool=True,
                confidence=0.9,
                intent="multi_step",
            )

        # 5. Coding Cognition Deliberation
        from services.coding.cognition import CodingSubIntent, coding_cognition

        is_coding, coding_sub_intent, coding_conf = coding_cognition.classify_coding_intent(
            user_input, context=context
        )
        if is_coding:
            coding_tools = coding_cognition.get_tools_for_sub_intent(coding_sub_intent)
            requires_plan = coding_sub_intent in {
                CodingSubIntent.EXPLORE,
                CodingSubIntent.DIAGNOSE,
                CodingSubIntent.PROPOSE,
                CodingSubIntent.MODIFY,
                CodingSubIntent.TEST,
            }
            return ReasoningDecision(
                task_type=TaskType.CODING,
                requires_planning=requires_plan,
                tools_needed=coding_tools,
                selected_capabilities=coding_tools,
                requires_tool=bool(coding_tools),
                confidence=coding_conf,
                intent="coding",
                coding_sub_intent=coding_sub_intent,
            )

        # 6. Fallback Complex Request
        if complexity == "complex":
            return ReasoningDecision(
                task_type=TaskType.MULTI_STEP,
                requires_planning=True,
                tools_needed=["terminal"],
                selected_capabilities=["terminal"],
                requires_tool=True,
                confidence=0.9,
                intent="multi_step",
            )

        # 5. Informational Queries (General knowledge / explanations)
        return ReasoningDecision(
            task_type=TaskType.INFORMATIONAL,
            requires_planning=False,
            confidence=0.95,
            intent="informational",
        )

    def decide(self, request: Request) -> ReasoningDecision:
        """Alias for compatibility with Request objects."""
        return self.reason(request)


reasoning_engine = ReasoningEngine()
