from typing import Any

from google import genai
import httpx

from services.brain.prompt_builder import prompt_builder
from services.configuration.settings import settings
from services.logging.logger import logger
from services.memory.conversation import Message


class AIGateway:
    """Gateway between ECHO and configured AI providers."""

    def __init__(self) -> None:
        self._gemini_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None:
            if not settings.gemini_api_key:
                raise RuntimeError("Gemini API key is not configured.")

            self._gemini_client = genai.Client(
                api_key=settings.gemini_api_key
            )

        return self._gemini_client

    async def generate(
        self,
        messages: list[Message],
        tool_result: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        code_context: str | None = None,
    ) -> str:
        if code_context is not None:
            try:
                prompt = prompt_builder.build(
                    messages,
                    tool_result=tool_result,
                    tools=tools,
                    code_context=code_context,
                )
            except TypeError:
                prompt = prompt_builder.build(
                    messages,
                    tool_result=tool_result,
                    tools=tools,
                )
        else:
            prompt = prompt_builder.build(
                messages,
                tool_result=tool_result,
                tools=tools,
            )



        if settings.ai_provider == "gemini":
            return await self._generate_gemini(prompt)

        return await self._generate_ollama(prompt)

    async def _generate_ollama(self, prompt: str) -> str:
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
            logger.error(
                "Ollama AI Gateway request failed: {}",
                exc,
            )
            return "I couldn't reach the AI service right now."

        response.raise_for_status()

        data: dict[str, Any] = response.json()

        return str(data["response"])

    async def _generate_gemini(self, prompt: str) -> str:
        try:
            client = self._get_gemini_client()

            interaction = await client.aio.interactions.create(
                model=settings.gemini_model,
                input=prompt,
            )

            return str(interaction.output_text)

        except Exception as exc:
            logger.error(
                "Gemini AI Gateway request failed: {}",
                exc,
            )
            return "I couldn't reach the AI service right now."


ai_gateway = AIGateway()