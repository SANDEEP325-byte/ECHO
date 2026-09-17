from typing import Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    response: str


# Fact Memory Schemas

class FactCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)


class FactResponse(BaseModel):
    key: str
    value: str


class FactsListResponse(BaseModel):
    facts: dict[str, str]


# Message / Conversation Schemas

class MessageResponse(BaseModel):
    role: str
    content: str


class MessagesListResponse(BaseModel):
    messages: list[MessageResponse]


# Semantic Memory Schemas

class SemanticCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    collection: str = Field(default="knowledge", min_length=1)
    id: str | None = None


class SemanticCreateResponse(BaseModel):
    id: str
    content: str
    metadata: dict[str, Any] | None = None
    collection: str


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=100)
    collection: str = Field(default="knowledge", min_length=1)


class SemanticSearchResult(BaseModel):
    id: str
    content: str
    metadata: dict[str, Any] | None = None
    distance: float | None = None


class SemanticSearchResponse(BaseModel):
    results: list[SemanticSearchResult]


# Management Schemas

class MemoryActionResponse(BaseModel):
    success: bool = True
    message: str = ""


# Action Confirmation Schemas

class ActionConfirmRequest(BaseModel):
    action_id: str = Field(min_length=1)


class ActionCancelRequest(BaseModel):
    action_id: str = Field(min_length=1)


class ActionConfirmationResponse(BaseModel):
    success: bool
    status: str
    action_id: str | None = None
    message: str
    result: Any = None
    error: str | None = None
    pending_action: dict[str, Any] | None = None


class PendingActionDetailResponse(BaseModel):
    action_id: str
    tool: str
    step_number: int | None = None
    arguments: dict[str, Any]
    risk_level: str
    created_at: float
    expires_at: float
    state: str
    request_id: str | None = None