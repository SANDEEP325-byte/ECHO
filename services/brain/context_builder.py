from packages.interfaces.request import Request
from services.logging.logger import logger
from services.memory.facts import fact_memory
from services.memory.persistent import persistent_memory


class ContextBuilder:
    """Builds relevant context for an ECHO request."""

    def build(
        self,
        request: Request,
        memory=persistent_memory,
        facts=fact_memory,
    ) -> Request:
        logger.info(
            "Building context for request {}",
            request.request_id,
        )

        recent_messages = memory.get_recent_messages(
            limit=6
        )

        saved_facts = facts.get_all_facts()

        request.context = {
            "recent_messages": recent_messages,
            "facts": saved_facts,
            "source": request.source,
            "session_id": request.session_id,
        }

        logger.info(
            "Context built for request {}: {} messages, {} facts",
            request.request_id,
            len(recent_messages),
            len(saved_facts),
        )

        return request


context_builder = ContextBuilder()