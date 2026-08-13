from typing import Any

import httpx

from services.configuration.settings import settings
from services.memory.conversation import Message


class AIGateway:
    """Gateway between ECHO and the configured local AI model."""

    async def generate(
        self,
        messages: list[Message],
    ) -> str:
        prompt = self._build_prompt(messages)

        payload: dict[str, Any] = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_host}/api/generate",
                json=payload,
            )

        response.raise_for_status()

        data: dict[str, Any] = response.json()

        return str(data["response"])

    @staticmethod
    def _build_prompt(messages: list[Message]) -> str:
        lines: list[str] = [
            "You are ECHO, a helpful personal AI assistant.",
            "Respond naturally and accurately.",
            "",
        ]

        for message in messages:
            if message.role == "user":
                lines.append(f"User: {message.content}")
            elif message.role == "assistant":
                lines.append(f"ECHO: {message.content}")

        lines.append("ECHO:")

        return "\n".join(lines)


ai_gateway = AIGateway()