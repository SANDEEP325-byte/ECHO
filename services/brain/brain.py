from services.brain.gateway import ai_gateway
from services.brain.intent_router import Intent, intent_router
from services.brain.tool_router import tool_router
from services.logging.logger import logger
from services.memory.conversation import Message
from services.memory.persistent import persistent_memory


class ECHOBrain:
    """Central coordinator for ECHO's reasoning and tool execution."""
    
    @staticmethod
    def _fixed_response(intent: Intent) -> str | None:
        if intent == Intent.GREETING:
            return "Hello! I'm ECHO, your personal AI assistant. How can I help you today? 😊"
        
        if intent == Intent.IDENTITY:
            return "I'm ECHO, your personal AI assistant.😊"
        
        return None
    
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
        
        intent = intent_router.classify(user_message)
        
        logger.info("Detected intent: {}", intent.value)
        
        # Handle deterministic intents without using the LLM.
        fixed_response = self._fixed_response(intent)
        
        if fixed_response is not None:
            response = fixed_response
            
        else:
            tool_result: str | None = None
            
            if tool_router.should_use_calculator(user_message):
                result = tool_router.execute_calculator(user_message)
                tool_result = str(result)
            
                logger.info(
                    "Brain received calculator result: {}",
                    tool_result,
                )
            
            response = await ai_gateway.generate(
                messages,
                tool_result=tool_result,
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