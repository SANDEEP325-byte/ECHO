from typing import Any
from fastapi import APIRouter, HTTPException, Query, status

from services.api.schemas import (
    FactCreateRequest,
    FactResponse,
    FactsListResponse,
    MemoryActionResponse,
    MessageResponse,
    MessagesListResponse,
    SemanticCreateRequest,
    SemanticCreateResponse,
    SemanticSearchRequest,
    SemanticSearchResult,
    SemanticSearchResponse,
)
from services.logging.logger import logger
from services.memory.manager import memory_manager

memory_router = APIRouter(prefix="/memory", tags=["memory"])


# Fact Memory Endpoints

@memory_router.post(
    "/facts",
    response_model=FactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_fact(request: FactCreateRequest) -> FactResponse:
    key = request.key.strip()
    value = request.value.strip()
    if not key or not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Key and value cannot be empty.",
        )

    memory_manager.save_fact(key, value)
    logger.info("Saved fact via API: key='{}'", key)
    return FactResponse(key=key, value=value)


@memory_router.get(
    "/facts",
    response_model=FactsListResponse,
)
async def get_all_facts() -> FactsListResponse:
    facts = memory_manager.get_all_facts()
    return FactsListResponse(facts=facts)


@memory_router.get(
    "/facts/{key}",
    response_model=FactResponse,
)
async def get_fact(key: str) -> FactResponse:
    value = memory_manager.get_fact(key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact '{key}' not found.",
        )
    return FactResponse(key=key, value=value)


@memory_router.delete(
    "/facts/{key}",
    response_model=MemoryActionResponse,
)
async def delete_fact(key: str) -> MemoryActionResponse:
    memory_manager.delete_fact(key)
    logger.info("Deleted fact via API: key='{}'", key)
    return MemoryActionResponse(
        success=True,
        message=f"Fact '{key}' deleted.",
    )


@memory_router.delete(
    "/facts",
    response_model=MemoryActionResponse,
)
async def clear_facts() -> MemoryActionResponse:
    memory_manager.clear_facts()
    logger.info("Cleared all facts via API")
    return MemoryActionResponse(
        success=True,
        message="All facts cleared.",
    )


# Persistent & Conversation Memory Endpoints

@memory_router.get(
    "/messages",
    response_model=MessagesListResponse,
)
async def get_messages(
    limit: int = Query(default=20, ge=1, le=100)
) -> MessagesListResponse:
    messages = memory_manager.get_recent_messages(limit=limit)
    return MessagesListResponse(
        messages=[
            MessageResponse(role=m["role"], content=m["content"])
            for m in messages
        ]
    )


@memory_router.delete(
    "/messages",
    response_model=MemoryActionResponse,
)
async def clear_messages() -> MemoryActionResponse:
    memory_manager.clear_persistent_memory()
    logger.info("Cleared persistent messages via API")
    return MemoryActionResponse(
        success=True,
        message="Persistent messages cleared.",
    )


@memory_router.get(
    "/conversation",
    response_model=MessagesListResponse,
)
async def get_conversation() -> MessagesListResponse:
    messages = memory_manager.get_conversation()
    return MessagesListResponse(
        messages=[
            MessageResponse(role=m.role, content=m.content)
            for m in messages
        ]
    )


@memory_router.delete(
    "/conversation",
    response_model=MemoryActionResponse,
)
async def clear_conversation() -> MemoryActionResponse:
    memory_manager.clear_conversation()
    logger.info("Cleared active conversation via API")
    return MemoryActionResponse(
        success=True,
        message="Conversation memory cleared.",
    )


# Semantic Memory Endpoints

@memory_router.post(
    "/semantic",
    response_model=SemanticCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_semantic_memory(
    request: SemanticCreateRequest,
) -> SemanticCreateResponse:
    content = request.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Content cannot be empty.",
        )

    try:
        mem_id = memory_manager.add_semantic_memory(
            content=content,
            metadata=request.metadata,
            collection=request.collection,
            memory_id=request.id,
        )
    except Exception as exc:
        logger.error("Failed to add semantic memory: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store semantic memory.",
        )

    return SemanticCreateResponse(
        id=mem_id,
        content=content,
        metadata=request.metadata,
        collection=request.collection,
    )


@memory_router.post(
    "/semantic/search",
    response_model=SemanticSearchResponse,
)
async def search_semantic_memory(
    request: SemanticSearchRequest,
) -> SemanticSearchResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query cannot be empty.",
        )

    results = memory_manager.search_semantic_memory(
        query=query,
        limit=request.limit,
        collection=request.collection,
    )

    formatted = [
        SemanticSearchResult(
            id=r["id"],
            content=r["content"],
            metadata=r.get("metadata"),
            distance=r.get("distance"),
        )
        for r in results
    ]

    return SemanticSearchResponse(results=formatted)


@memory_router.delete(
    "/semantic/{memory_id}",
    response_model=MemoryActionResponse,
)
async def delete_semantic_memory(
    memory_id: str,
    collection: str = Query(default="knowledge", min_length=1),
) -> MemoryActionResponse:
    deleted = memory_manager.delete_semantic_memory(
        memory_id=memory_id,
        collection=collection,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semantic memory '{memory_id}' not found in collection '{collection}'.",
        )

    return MemoryActionResponse(
        success=True,
        message=f"Semantic memory '{memory_id}' deleted.",
    )


@memory_router.delete(
    "/semantic",
    response_model=MemoryActionResponse,
)
async def clear_semantic_memory(
    collection: str | None = Query(default=None),
) -> MemoryActionResponse:
    memory_manager.clear_semantic_memory(collection=collection)
    msg = (
        f"Semantic collection '{collection}' cleared."
        if collection
        else "All semantic memory collections cleared."
    )
    logger.info("Cleared semantic memory via API: {}", msg)
    return MemoryActionResponse(success=True, message=msg)


# Full Memory Wipe

@memory_router.post(
    "/wipe",
    response_model=MemoryActionResponse,
)
async def wipe_all_memory() -> MemoryActionResponse:
    memory_manager.clear_all()
    logger.info("Full memory wipe executed via API")
    return MemoryActionResponse(
        success=True,
        message="All memory subsystems wiped successfully.",
    )
