from typing import Any

import httpx

from services.configuration.settings import settings
from services.memory.conversation import Message


class AIGateway:
    """Gateway between ECHO and the configured local AI model."""

    async def generate(
        self,
        messages: list[Message],
        tool_result: str | None = None,
    ) -> str:
        prompt = self._build_prompt(
            messages,
            tool_result=tool_result,
            )

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
    def _build_prompt(
        messages: list[Message],
        tool_result: str | None = None,
    ) -> str:
        lines: list[str] = [
            "You are ECHO, a personal AI assistant.",
            "Your name is ECHO.",
            "You are helpful, friendly, and conversational.",
            "Always identify yourself as ECHO when asked who you are.",
            "Answer the user's latest message directly.",
            "Do not repeat the user's question.",
            "Do not invent information.",
            "Keep simple answers concise but natural.",
            "For greetings, respond naturally and warmly.",
            "",
            "Conversation:",
        ]

        for message in messages:
            if message.role == "user":
                lines.append(f"User: {message.content}")
            elif message.role == "assistant":
                lines.append(f"ECHO: {message.content}")
       
        if tool_result is not None:
            lines.extend(
                [
                    "",
                    f"Tool result: {tool_result}",
                    "Use this result as the factual answer.",
                    "Do not recalculate or change thee tool result.",
                ]
            )

        lines.extend(
            [
                "",
                "Answer only the latest user message.",
                "ECHO:",
            ]
        )

        return "\n".join(lines)


ai_gateway = AIGateway()