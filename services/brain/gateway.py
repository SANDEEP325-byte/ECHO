from typing import Any

import httpx

from services.configuration.settings import settings
from services.memory.conversation import Message
from services.brain.prompt_builder import prompt_builder
from services.logging.logger import logger

class AIGateway:
    """Gateway between ECHO and the configured local AI model."""

    async def generate(
        self,
        messages: list[Message],
        tool_result: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        prompt = prompt_builder.build(
            messages,
            tool_result=tool_result,
            tools=tools,
        )

        payload: dict[str, Any] = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{settings.ollama_host}/api/generate",
                    json=payload,
                )
        except Exception as exc:
            logger.error("AI Gateway request failed: {}", exc)
            return "I couldn't reach the AI service right now."

        response.raise_for_status()

        data: dict[str, Any] = response.json()

        return str(data["response"])

ai_gateway = AIGateway()