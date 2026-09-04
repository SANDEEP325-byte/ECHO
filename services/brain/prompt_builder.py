from typing import Any
from services.memory.conversation import Message
from services.logging.logger import logger

class PromptBuilder:
    """Builds the final prompt sent to ECHO's AI model."""

    @staticmethod
    def build(
        messages: list[Message],
        tool_result: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        logger.info(
            "Building AI prompt: messages={}, tools={}, tool_result={}",
            len(messages),
            len(tools or []),
            tool_result is not None,
        )

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
        ]

        if tools:
            lines.extend(
                [
                    "",
                    "Available tools:",
                ]
            )

            for tool in tools:
                lines.append(
                    f"- {tool['name']}: {tool['description']}"
                )

        lines.extend(
            [
                "",
                "Conversation:",
            ]
        )

        for message in messages:
            if message.role == "system":
                lines.append(message.content)

            elif message.role == "user":
                lines.append(
                    f"User: {message.content}"
                )

            elif message.role == "assistant":
                lines.append(
                    f"ECHO: {message.content}"
                )

        if tool_result is not None:
            lines.extend(
                [
                    "",
                    f"Tool result: {tool_result}",
                    "Use this result as the factual answer.",
                    "Do not recalculate or change the tool result.",
                ]
            )

        lines.extend(
            [
                "",
                "Answer only the latest user message.",
                "ECHO:",
            ]
        )

        prompt = "\n".join(lines)

        logger.info(
            "AI prompt built successfully: {} characters",
            len(prompt),
        )

        return prompt

prompt_builder = PromptBuilder()