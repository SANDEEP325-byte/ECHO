import re

from services.brain.gateway import ai_gateway
from services.brain.intent_router import Intent
from services.brain.tool_router import tool_router
from services.logging.logger import logger
from services.memory.conversation import Message
from services.memory.facts import fact_memory
from services.memory.persistent import persistent_memory
from services.memory.manager import memory_manager
from packages.interfaces.request import Request, RequestStatus
from services.brain.context_builder import context_builder
from services.brain.request_analyzer import request_analyzer
from services.brain.planner import planner
from services.brain.execution import execution_engine
from services.brain.verification import verification_engine
from services.brain.tool_selector import tool_selector

class ECHOBrain:
    """Central coordinator for ECHO's reasoning and tool execution."""
    
    def __init__(
        self,
        memory_manager=None,
    ) -> None:
        self.memory_manager = memory_manager
        
    @staticmethod
    def _clean_memory_value(value: str) -> str:
        return value.strip().rstrip(".,!?;:")

    @staticmethod
    def _save_memory(
        user_message: str,
        memory_manager=None,
    ) -> str | None:
        normalized = user_message.strip()

        name_patterns = [
            r"my name is (.+)",
            r"i(?:'m| am) (.+)",
            r"actually, my name is (.+)",
            r"actually my name is (.+)",
            r"no, my name is (.+)",
            r"no my name is (.+)",
        ]

        for pattern in name_patterns:
            match = re.fullmatch(pattern, normalized, re.IGNORECASE)

            if match:
                name = ECHOBrain._clean_memory_value(match.group(1))

                if name:
                    if memory_manager is not None:
                        memory_manager.save_fact("name", name)
                    else:
                        fact_memory.save_fact("name", name)

                    return (
                        f"Got it! Your name is {name}. "
                        "I'll remember that.😉"
                    )

        preferred_name_patterns = [
            r"call me (.+)",
            r"(?:actually, )?call me (.+)",
            r"you can call me (.+)",
            r"I want you to call me (.+)",
            r"actually, call me (.+)",
            r"actually call me (.+)",
            r"i actually prefer to be called (.+)",
            r"from now on, call me (.+)",
            r"from now on call me (.+)",
        ]

        for pattern in preferred_name_patterns:
            match = re.fullmatch(pattern, normalized, re.IGNORECASE)

            if match:
                preferred_name = ECHOBrain._clean_memory_value(
                    match.group(1)
                )

                if preferred_name:
                    if memory_manager is not None:
                        memory_manager.save_fact(
                            "preferred_name",
                            preferred_name,
                        )
                    else:
                        fact_memory.save_fact(
                            "preferred_name",
                            preferred_name,
                        )

                    return (
                        f"Got it! I'll call you {preferred_name}. "
                        "I'll remember that. 🫡"
                    )

        color_patterns = [
            r"my favorite color is actually (.+)",
            r"my favourite color is actually (.+)",

            r"actually, my favorite color is (.+)",
            r"actually my favorite color is (.+)",
            r"actually, my favourite color is (.+)",
            r"actually my favourite color is (.+)",

            r"my favorite color is (.+)",
            r"my favourite color is (.+)",
        ]

        for pattern in color_patterns:
            match = re.fullmatch(pattern, normalized, re.IGNORECASE)

            if match:
                color = ECHOBrain._clean_memory_value(
                    match.group(1)
                )

                if color:
                    if memory_manager is not None:
                        memory_manager.save_fact("favorite_color", color)
                    else:
                        fact_memory.save_fact("favorite_color", color)

                    return (
                        f"Got it! Your favorite color is {color}. "
                        "I'll remember that. 🫡"
                    )
        return None

    @staticmethod
    def _recall_memory(
        user_message: str,
        memory_manager=None,
    ) -> str:
        normalized = user_message.lower().strip()

        if (
            "what is my name" in normalized
            or "what's my name" in normalized
            or "whats my name" in normalized
            or "do you know my name" in normalized
        ):
            if memory_manager is not None:
                value = memory_manager.get_fact("name")
            else:
                value = fact_memory.get_fact("name")

            if value is not None:
                return f"Your name is {value}. 😌"

            return "I don't know your name yet."

        if (
            "what should you call me" in normalized
            or "what do you call me" in normalized
            or "what is my preferred name" in normalized
            or "what's my preferred name" in normalized
            or "what name should you use" in normalized
        ):
            if memory_manager is not None:
                value = memory_manager.get_fact("preferred_name")
            else:
                value = fact_memory.get_fact("preferred_name")

            if value is not None:
                return f"I'll call you {value}. 😉"

            return "You haven't told me what you'd like me to call you yet."

        if (
            "favorite color" in normalized
            or "favourite color" in normalized
        ):
            if memory_manager is not None:
                value = memory_manager.get_fact("favorite_color")
            else:
                value = fact_memory.get_fact("favorite_color")

            if value is not None:
                return f"Your favorite color is {value}. 🫟"

            return "I don't know your favorite color yet."

        if memory_manager is not None:
            facts = memory_manager.get_all_facts()
        else:
            facts = fact_memory.get_all_facts()

        if not facts:
            return "I don't have any saved information about you yet."

        parts = []

        if "name" in facts:
            parts.append(f"your name is {facts['name']}")

        if "preferred_name" in facts:
            parts.append(f"you prefer to be called {facts['preferred_name']}")

        if "favorite_color" in facts:
            parts.append(f"your favorite color is {facts['favorite_color']}")

        if not parts:
            return (
                "I remember some information about you, "
                "but I don't have enough details to summarize it yet."
            )


        if len(parts) == 1:
            summary = parts[0]

        elif len(parts) == 2:
            summary = f"{parts[0]} and {parts[1]}"

        else:
            summary = ", ".join(parts[:-1]) + f", and {parts[-1]}"

        return f"I remember that {summary}. 🫡"

    @staticmethod
    def _delete_memory(
        user_message: str,
        memory_manager=None,
    ) -> str:
        normalized = user_message.lower().strip()

        if (
            "forget everything" in normalized
            or "forget all my memories" in normalized
            or "forget all my information" in normalized
        ):
            if memory_manager is not None:
                memory_manager.clear_facts()
            else:
                fact_memory.clear()

            return "Okay, I've forgotten everything I remember about you."

        if "name" in normalized:
            if memory_manager is not None:
                memory_manager.delete_fact("name")
            else:
                fact_memory.delete_fact("name")

            return "Okay, I've forgotten your name."

        if (
            "favorite color" in normalized
            or "favourite color" in normalized
        ):
            if memory_manager is not None:
                memory_manager.delete_fact("favorite_color")
            else:
                fact_memory.delete_fact("favorite_color")

            return "Okay, I've forgotten your favorite color."

        if (
            "call me" in normalized
            or "preferred name" in normalized
        ):
            if memory_manager is not None:
                memory_manager.delete_fact("preferred_name")
            else:
                fact_memory.delete_fact("preferred_name")

            return "Okay, I've forgotten what you'd like me to call you."

        return "I don't know which memory you want me to forget."
    
    @staticmethod
    def _fixed_response(
        intent: Intent,
        memory_manager=None,
    ) -> str | None:
        if memory_manager is not None:
            preferred_name = memory_manager.get_fact("preferred_name")
        else:
            preferred_name = fact_memory.get_fact("preferred_name")

        if intent == Intent.GREETING:
            if preferred_name:
                return (
                    f"Hello {preferred_name}! I'm ECHO, "
                    "your personal AI assistant. How can I help you today? 😊"
                )

            return (
                "Hello! I'm ECHO, your personal AI assistant. "
                "How can I help you today? 😊"
            )

        if intent == Intent.IDENTITY:
            return "I'm ECHO, your personal AI assistant. 😌"

        return None

    @staticmethod
    def _execute_tool_for_intent(
        intent: Intent,
        user_message: str,
    ) -> str | None:
        tool_name = tool_router.get_tool_for_intent(
            intent.value
        )

        if tool_name is None:
            return None

        result = tool_router.execute_for_intent(
            intent.value,
            user_message,
        )

        logger.info(
            "Brain received {} tool result: {}",
            tool_name,
            result,
        )

        return str(result)

    async def process(self, user_message: str) -> str:
        logger.info("Brain processing request")

        request = Request(
            user_input=user_message,
        )

        try:
            request = request_analyzer.analyze(request)
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)

            logger.error(
                "Request analysis failed for request {}: {}",
                request.request_id,
                exc,
            )

            return "I couldn't process your request because an internal component failed."
        try:
            if self.memory_manager is not None:
                request = context_builder.build(
                    request,
                    memory_manager=self.memory_manager,
                )
            else:
                request = context_builder.build(
                    request,
                    memory=persistent_memory,
                    facts=fact_memory,
                )
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)

            logger.error(
                "Context building failed for request {}: {}",
                request.request_id,
                exc,
            )

            return "I couldn't process your request because an internal component failed."

        try:
            plan = planner.create_plan(
                request.user_input,
                requires_planning=request.complexity == "complex",
            )
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)

            logger.error(
                "Planning failed for request {}: {}",
                request.request_id,
                exc,
            )

            return "I couldn't process your request because an internal component failed."

        request.plan = [
            {
                "step": step.step_number,
                "description": step.description,
            }
            for step in plan.steps
        ]

        request.status = RequestStatus.PLANNING if plan.requires_planning else request.status

        try:
            request = tool_selector.select(
                request,
                plan,
            )
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)

            logger.error(
                "Tool selection failed for request {}: {}",
                request.request_id,
                exc,
            )

            return "I couldn't process your request because an internal component failed."

        logger.info(
            "Request {} planning complete: requires_planning={}, steps={}",
            request.request_id,
            plan.requires_planning,
            len(plan.steps),
        )

        execution_result = None
        verification_result = None
        response = None

        if plan.requires_planning:
            try:
                execution_result = execution_engine.execute(
                    request,
                    plan,
                )
            except Exception as exc:
                request.status = RequestStatus.FAILED
                request.error = str(exc)

                logger.error(
                    "Execution failed for request {}: {}",
                    request.request_id,
                    exc,
                )

                return "I couldn't process your request because an internal component failed."

            if not execution_result.success:
                request.status = RequestStatus.FAILED
                request.error = execution_result.error

                logger.error(
                    "Execution failed for request {}: {}",
                    request.request_id,
                    execution_result.error,
                )

                return execution_result.error

            try:
                verification_result = verification_engine.verify(
                    request,
                    execution_result,
                )
            except Exception as exc:
                request.status = RequestStatus.FAILED
                request.error = str(exc)

                logger.error(
                    "Verification failed for request {}: {}",
                    request.request_id,
                    exc,
                )

                return "I couldn't process your request because an internal component failed."

            if not verification_result.success:
                request.status = RequestStatus.FAILED
                request.error = verification_result.error

                logger.error(
                    "Verification failed for request {}: {}",
                    request.request_id,
                    verification_result.error,
                )

                return verification_result.error

            request.status = RequestStatus.COMPLETED
            response = execution_result.result

        messages = [
            Message(
                role=message["role"],
                content=message["content"],
            )
            for message in request.context["recent_messages"]
        ]

        messages.append(
            Message(
                role="user",
                content=user_message,
            )
        )

        facts = request.context.get("facts", {})

        if facts:
            memory_lines = ["Known facts about the user:"]

            for key, value in facts.items():
                memory_lines.append(f"- {key}: {value}")

            messages.insert(
                0,
                Message(
                    role="system",
                    content="\n".join(memory_lines),
                ),
            )

        semantic_memories = request.context.get("semantic_memories", [])

        if semantic_memories:
            semantic_lines = ["Relevant context from memory:"]

            for item in semantic_memories:
                content = item.get("content") or item.get("document") or item.get("text", "")
                if content:
                    semantic_lines.append(f"- {content}")

            if len(semantic_lines) > 1:
                messages.insert(
                    0,
                    Message(
                        role="system",
                        content="\n".join(semantic_lines),
                    ),
                )

        intent = Intent(request.intent)

        logger.info("Detected intent: {}", intent.value)

        tool_name = tool_router.get_tool_for_intent(intent.value)

        if tool_name:
            logger.info(
                "Intent mapped to tool: {}",
                tool_name,
            )

        # Handle deterministic intents without using the LLM.
        fixed_response = self._fixed_response(
            intent,
            memory_manager=self.memory_manager,
        )
        if fixed_response is not None:
            response = fixed_response

        elif intent == Intent.MEMORY_SAVE:
            response = self._save_memory(
                user_message,
                memory_manager=self.memory_manager,
            )

        elif intent == Intent.MEMORY_RECALL:
            response = self._recall_memory(
                user_message,
                memory_manager=self.memory_manager,
            )

        elif intent == Intent.MEMORY_DELETE:
            response = self._delete_memory(
                user_message,
                memory_manager=self.memory_manager,
            )

        elif response is not None:
            pass

        else:
            tool_result = self._execute_tool_for_intent(
                intent,
                user_message,
            )

            if tool_result is not None:
                if intent == Intent.CALCULATOR:
                    response = f"The result is {tool_result}."
                elif intent == Intent.TIME:
                    response = f"The current time is {tool_result}."
                elif intent == Intent.DATE:
                    response = f"Today's date is {tool_result}."
                else:
                    response = tool_result
            else:
                try:
                    response = await ai_gateway.generate(
                        messages,
                        tools=tool_router.get_available_tools(),
                    )
                except Exception as exc:
                    request.status = RequestStatus.FAILED
                    request.error = str(exc)
                    logger.error(
                        "AI Gateway failed for request {}: {}",
                        request.request_id,
                        exc,
                    )
                    return "I couldn't process your request because an internal component failed."

        if self.memory_manager is not None:
            self.memory_manager.save_message(
                role="user",
                content=user_message,
            )

            self.memory_manager.save_message(
                role="assistant",
                content=response,
            )
        else:
            persistent_memory.save_message(
                role="user",
                content=user_message,
            )

            persistent_memory.save_message(
                role="assistant",
                content=response,
            )

        logger.info("Brain completed request")
        return response

echo_brain = ECHOBrain(
    memory_manager=memory_manager,
)