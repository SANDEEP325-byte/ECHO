import json
import re
from typing import Any

from packages.common.capability_registry import capability_registry
from packages.interfaces.plan import Plan, PlanStep
from services.logging.logger import logger


class Planner:
    """Creates a structured execution plan from an analyzed user request."""

    def __init__(self, ai_gateway: Any = None) -> None:
        self.ai_gateway = ai_gateway

    @staticmethod
    def _parse_plan_json(raw_text: str) -> list[PlanStep] | None:
        """Defensively extract and parse a JSON plan array or object from model response."""
        try:
            # Match JSON list or object with steps
            match = re.search(r"(\[\s*\{.*\}\s*\]|\{\s*\"steps\".*\})", raw_text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group(0))
            if isinstance(data, dict) and "steps" in data:
                data = data["steps"]
            if not isinstance(data, list) or not data:
                return None

            steps: list[PlanStep] = []
            for idx, item in enumerate(data, 1):
                if not isinstance(item, dict):
                    continue
                step_num = item.get("step_number", idx)
                desc = item.get("description", f"Step {step_num}")
                raw_tool = item.get("tool_name") or item.get("tool")
                args = item.get("arguments", {})
                purpose = item.get("purpose")

                # Validate tool against capability registry
                if raw_tool and capability_registry.is_available(str(raw_tool)):
                    tool_val = str(raw_tool)
                else:
                    tool_val = None

                steps.append(
                    PlanStep(
                        step_number=int(step_num),
                        description=str(desc),
                        tool_name=tool_val,
                        arguments=dict(args) if isinstance(args, dict) else {},
                        purpose=str(purpose) if purpose else None,
                    )
                )
            return steps if steps else None
        except Exception as exc:
            logger.warning("Failed to parse dynamic plan JSON: {}", exc)
            return None

    @classmethod
    def _deterministic_plan(
        cls,
        user_message: str,
        reasoning_decision: Any = None,
    ) -> list[PlanStep]:
        """Provides a safe, deterministic plan for known tasks."""
        normalized = user_message.strip().lower()

        if "create" in normalized and "run" in normalized:
            return [
                PlanStep(
                    step_number=1,
                    description="Create the requested project or resource.",
                    tool_name="terminal",
                    purpose="Initialize project structure",
                    arguments={"command": "create"},
                ),
                PlanStep(
                    step_number=2,
                    description="Create or configure the required files.",
                    tool_name="terminal",
                    purpose="Configure dependencies",
                    arguments={"command": "configure"},
                ),
                PlanStep(
                    step_number=3,
                    description="Run the requested project or command.",
                    tool_name="terminal",
                    purpose="Start execution",
                    arguments={"command": "run"},
                ),
                PlanStep(
                    step_number=4,
                    description="Verify that the operation completed successfully.",
                    purpose="Validate result",
                ),
            ]

        # Check for Coding Task Plan
        from services.coding.cognition import coding_cognition

        is_coding = False
        sub_intent = None
        if reasoning_decision is not None and getattr(reasoning_decision, "task_type", None) == "coding":
            is_coding = True
            sub_intent = getattr(reasoning_decision, "coding_sub_intent", None)
        elif reasoning_decision is None or getattr(reasoning_decision, "task_type", None) != "multi_step":
            is_coding, sub_intent, _ = coding_cognition.classify_coding_intent(user_message)

        if is_coding:
            coding_steps = coding_cognition.build_coding_plan(user_message, sub_intent=sub_intent)
            if coding_steps:
                return coding_steps

        return [
            PlanStep(
                step_number=1,
                description="Analyze and execute the requested task.",
                purpose="Execute task core",
            ),
            PlanStep(
                step_number=2,
                description="Verify the result.",
                purpose="Verify output",
            ),
        ]

    async def create_plan_async(
        self,
        user_message: str,
        requires_planning: bool,
        ai_gateway: Any = None,
        reasoning_decision: Any = None,
    ) -> Plan:
        """Asynchronously creates an execution plan, attempting structured model planning if available."""
        if not requires_planning:
            return Plan(requires_planning=False, steps=[])

        gateway = ai_gateway or self.ai_gateway
        if gateway is not None:
            try:
                plan_prompt = (
                    "You are ECHO's task planning system. Decompose this request into structured steps.\n"
                    f"User request: {user_message}\n\n"
                    "Output ONLY a valid JSON array of steps formatted exactly like:\n"
                    '[{"step_number": 1, "description": "...", "tool_name": null, "arguments": {}, "purpose": "..."}]\n'
                )
                from services.memory.conversation import Message

                raw_output = await gateway.generate(
                    [Message(role="user", content=plan_prompt)]
                )
                parsed = self._parse_plan_json(raw_output)
                if parsed:
                    logger.info("Generated dynamic structured plan with {} steps", len(parsed))
                    return Plan(requires_planning=True, steps=parsed)
            except Exception as exc:
                logger.warning("Dynamic planning failed, falling back to deterministic plan: {}", exc)

        return self.create_plan(user_message, requires_planning=True, reasoning_decision=reasoning_decision)

    @classmethod
    def create_plan(
        cls,
        user_message: str,
        requires_planning: bool,
        reasoning_decision: Any = None,
    ) -> Plan:
        """Synchronous plan creation using deterministic fallbacks."""
        if not requires_planning:
            return Plan(requires_planning=False, steps=[])

        steps = cls._deterministic_plan(user_message, reasoning_decision=reasoning_decision)
        return Plan(requires_planning=True, steps=steps)



planner = Planner()