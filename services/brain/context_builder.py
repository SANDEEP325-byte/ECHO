from packages.interfaces.request import Request
from services.logging.logger import logger
from services.memory.facts import fact_memory
from services.memory.manager import MemoryManager
from services.memory.persistent import persistent_memory


class ContextBuilder:
    """Builds relevant context for an ECHO request."""

    def build(
        self,
        request: Request,
        memory=persistent_memory,
        facts=fact_memory,
        memory_manager: MemoryManager | None = None,
    ) -> Request:
        logger.info(
            "Building context for request {}",
            request.request_id,
        )

        semantic_memories = []

        if memory_manager is not None:
            recent_messages = memory_manager.get_recent_messages(
                limit=6
            )

            saved_facts = memory_manager.get_all_facts()

            if request.user_input and hasattr(memory_manager, "search_semantic_memory"):
                try:
                    semantic_memories = memory_manager.search_semantic_memory(
                        query=request.user_input,
                        limit=3,
                    )
                except Exception as exc:
                    logger.warning("Semantic memory search failed: {}", exc)

        else:
            recent_messages = memory.get_recent_messages(
                limit=6
            )

            saved_facts = facts.get_all_facts()

        request.context = {
            "recent_messages": recent_messages,
            "facts": saved_facts,
            "semantic_memories": semantic_memories,
            "source": request.source,
            "session_id": request.session_id,
        }

        logger.info(
            "Context built for request {}: {} messages, {} facts, {} semantic memories",
            request.request_id,
            len(recent_messages),
            len(saved_facts),
            len(semantic_memories),
        )

        return request


context_builder = ContextBuilder()