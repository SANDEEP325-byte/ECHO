from dataclasses import dataclass, field


from typing import Any


@dataclass(frozen=True)
class PlanStep:
    step_number: int
    description: str
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    purpose: str | None = None


@dataclass(frozen=True)
class Plan:
    requires_planning: bool
    steps: list[PlanStep] = field(default_factory=list)