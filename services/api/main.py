from fastapi import FastAPI

from services.configuration.settings import settings
from services.logging.logger import logger

app = FastAPI(
    title="ECHO",
    version="0.1.0",
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