from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi import Request as FastAPIRequest
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.api.connection_manager import connection_manager
from services.api.live_gateway import live_router
from services.api.memory import memory_router
from services.api.schemas import (
    ActionCancelRequest,
    ActionConfirmationResponse,
    ActionConfirmRequest,
    ChatRequest,
    ChatResponse,
    PendingActionDetailResponse,
)
from services.brain.brain import echo_brain
from services.configuration.settings import settings
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.memory.database import initialize_database

initialize_database()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A modular, privacy-first Personal AI Operating System.",
)

app.include_router(memory_router)
app.include_router(live_router)

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "web"
if WEB_DIR.exists():
    app.mount("/hud", StaticFiles(directory=str(WEB_DIR), html=True), name="hud")


@app.on_event("startup")
async def startup_event() -> None:
    logger.info(f"{settings.app_name} v{settings.app_version} starting...")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info(f"{settings.app_name} shutting down...")
    await connection_manager.close_all()


@app.get("/")
async def root(request: FastAPIRequest) -> Any:
    accept = request.headers.get("accept", "")
    if accept.startswith("text/html") and WEB_DIR.exists() and (WEB_DIR / "index.html").exists():
        return FileResponse(str(WEB_DIR / "index.html"))
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "healthy",
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    logger.info("Received chat request")

    try:
        response = await echo_brain.process(request.message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Chat request failed: {}", exc)
        return ChatResponse(
            response="I couldn't process your request because an internal component failed."
        )

    logger.info("AI response generated")

    return ChatResponse(response=response)


@app.post("/actions/confirm", response_model=ActionConfirmationResponse)
async def confirm_action(req: ActionConfirmRequest) -> ActionConfirmationResponse:
    logger.info("Received action confirmation request: action_id={}", req.action_id)
    res = echo_brain.confirm_action(req.action_id)
    return ActionConfirmationResponse(
        success=res.success,
        status=res.status.value,
        action_id=res.action_id,
        message=res.message,
        result=res.result,
        error=res.error,
        pending_action=res.pending_action,
    )


@app.post("/actions/cancel", response_model=ActionConfirmationResponse)
async def cancel_action(req: ActionCancelRequest) -> ActionConfirmationResponse:
    logger.info("Received action cancellation request: action_id={}", req.action_id)
    res = echo_brain.cancel_action(req.action_id)
    return ActionConfirmationResponse(
        success=res.success,
        status=res.status.value,
        action_id=res.action_id,
        message=res.message,
        result=res.result,
        error=res.error,
        pending_action=res.pending_action,
    )


@app.get("/actions/{action_id}", response_model=PendingActionDetailResponse)
async def get_action_detail(action_id: str) -> PendingActionDetailResponse:
    action = echo_brain.get_pending_action(action_id)
    if action is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Pending action not found.")
    d = action.to_dict()
    return PendingActionDetailResponse(
        action_id=d["action_id"],
        tool=d["tool"],
        step_number=d.get("step_number"),
        arguments=d["arguments"],
        risk_level=d["risk_level"],
        created_at=d["created_at"],
        expires_at=d["expires_at"],
        state=d["state"],
        request_id=d.get("request_id"),
    )
