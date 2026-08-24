import re

from services.brain.gateway import ai_gateway
from services.brain.intent_router import Intent, intent_router
from services.brain.tool_router import tool_router
from services.logging.logger import logger
from services.memory.conversation import Message
from services.memory.facts import fact_memory
from services.memory.persistent import persistent_memory


class ECHOBrain:
    """Central coordinator for ECHO's reasoning and tool execution."""
    @staticmethod
    def _clean_memory_value(value: str) -> str:
        return value.strip().rstrip(".,!?;:")
    
    @staticmethod
    def _save_memory(user_message: str) -> str | None:
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
                    fact_memory.save_fact("name", name)
                    return (
                        f"Got it! Your name is {name}. "
                        "I'll remember that.😉")
                    
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
                    fact_memory.save_fact("favorite_color", color)
                    return (
                        f"Got it! Your favorite color is {color}. "
                        "I'll remember that. 🫡"
                    )
        return None
    
    @staticmethod
    def _recall_memory(user_message: str) -> str:
        normalized = user_message.lower().strip()
            
        if (
            "what is my name" in normalized
            or "what's my name" in normalized
            or "whats my name" in normalized
            or "do you know my name" in normalized
        ):
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
            value = fact_memory.get_fact("preferred_name")
            
            if value is not None:
                return f"I'll call you {value}. 😉"
            
            return "You haven't told me what you'd like me to call you yet."
        
        if (
            "favorite color" in normalized 
            or "favourite color" in normalized
        ):
            value = fact_memory.get_fact("favorite_color")
            
            if value is not None:
                return f"Your favorite color is {value}. 🫟"
            
            return "I don't know your favorite color yet."
        
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
    def _delete_memory(user_message: str) -> str:
        normalized = user_message.lower().strip()
        
        if (
            "forget everything" in normalized
            or "forget all my memories" in normalized
            or "forget all my information" in normalized
        ):
            fact_memory.clear()
            return "Okay, I've forgotten everything I remember about you."
        
        if "name" in normalized:
            fact_memory.delete_fact("name")
            return "Okay, I've forgotten your name."
        
        if (
            "favorite color" in normalized
            or "favourite color" in normalized
        ):
            fact_memory.delete_fact("favorite_color")
            return "Okay, I've forgotten your favorite color."
        
        if (
            "call me" in normalized
            or "preferred name" in normalized
        ):
            fact_memory.delete_fact("preferred_name")
            return "Okay, I've forgotten what you'd like me to call you."
        
        return "I don't know which memory you want me to forget."
        
    @staticmethod
    def _fixed_response(intent: Intent) -> str | None:
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
        
        stored_messages = persistent_memory.get_recent_messages(limit=6)
        
        messages = [
            Message(
                role=message["role"],
                content=message["content"],
            )
            for message in stored_messages
        ]
        
        messages.append(
            Message(
                role="user",
                content=user_message,
            )
        )
        
        memory_context = fact_memory.get_context()
        
        if memory_context:
            messages.insert(
                0,
                Message(
                    role="system",
                    content=memory_context,
                ),
            )
        
        intent = intent_router.classify(user_message)
        
        logger.info("Detected intent: {}", intent.value)
        
        tool_name = tool_router.get_tool_for_intent(intent.value)

        if tool_name:
            logger.info(
                "Intent mapped to tool: {}",
                tool_name,
            )
        
        # Handle deterministic intents without using the LLM.
        fixed_response = self._fixed_response(intent)
        
        if fixed_response is not None:
            response = fixed_response
        
        elif intent == Intent.MEMORY_SAVE:
            response = self._save_memory(user_message)
            
        elif intent == Intent.MEMORY_RECALL:
            response = self._recall_memory(user_message)
            
        elif intent == Intent.MEMORY_DELETE:
           response = self._delete_memory(user_message)
           
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
                response = await ai_gateway.generate(
                    messages,
                    tools=tool_router.get_available_tools(),
                )
                
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
    
echo_brain = ECHOBrain()