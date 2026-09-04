from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class RequestStatus(str, Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Request:
    user_input: str
    source: str = "chat"
    session_id: str | None = None

    request_id: str = field(
        default_factory=lambda: str(uuid4())
    )

    intent: str | None = None
    priority: str | None = None
    complexity: str | None = None

    context: dict[str, Any] = field(default_factory=dict)
    plan: list[dict[str, Any]] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)

    status: RequestStatus = RequestStatus.CREATED
    result: Any = None
    error: str | None = None