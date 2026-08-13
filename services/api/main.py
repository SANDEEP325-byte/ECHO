from fastapi import FastAPI

from services.api.schemas import ChatRequest, ChatResponse
from services.brain.gateway import ai_gateway
from services.configuration.settings import settings
from services.logging.logger import logger
from services.memory.conversation import conversation_memory
from services.memory.database import initialize_database
from services.memory.persistent import persistent_memory
from services.memory.conversation import Message

initialize_database()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A modular, privacy-first Personal AI Operating System.",
)

@app.on_event("startup")
async def startup_event() -> None:
    logger.info(
        f"{settings.app_name} v{settings.app_version} starting..."
    )

@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info(f"{settings.app_name} shutting down...")
    
    
@app.get("/")
async def root() -> dict[str, str]:
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
    
    persistent_memory.save_message(
        role="user",
        content=request.message,
    )
    
    stored_messages = persistent_memory.get_recent_messages(limit=20)
    
    messages = [
        Message(
            role=message["role"],
            content=message["content"],
        )
        for message in stored_messages
    ]
    
    response = await ai_gateway.generate(messages)
    
    persistent_memory.save_message(
        role="assistant",
        content=response,
    )
    
    logger.info("AI response generated")
    
    return ChatResponse(response=response)