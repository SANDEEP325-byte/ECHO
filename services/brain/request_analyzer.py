from packages.interfaces.request import Request, RequestStatus
from services.brain.intent_router import intent_router
from services.logging.logger import logger


class RequestAnalyzer:
    """Analyzes an ECHO request and enriches it with execution metadata."""

    def analyze(self, request: Request) -> Request:
        logger.info(
            "Analyzing request {}",
            request.request_id,
        )

        request.status = RequestStatus.ANALYZING

        intent = intent_router.classify(request.user_input)

        request.intent = intent.value
        request.priority = self._determine_priority(request.user_input)
        request.complexity = self._determine_complexity(
            request.user_input,
            intent.value,
        )

        logger.info(
            "Request {} analyzed: intent={}, priority={}, complexity={}",
            request.request_id,
            request.intent,
            request.priority,
            request.complexity,
        )

        return request

    @staticmethod
    def _determine_priority(user_input: str) -> str:
        normalized = user_input.lower()

        high_priority_keywords = (
            "urgent",
            "emergency",
            "critical",
            "immediately",
            "as soon as possible",
        )

        if any(
            keyword in normalized
            for keyword in high_priority_keywords
        ):
            return "high"

        return "normal"

    @staticmethod
    def _determine_complexity(
        user_input: str,
        intent: str,
    ) -> str:
        normalized = user_input.lower()

        if intent in {"greeting", "identity", "time", "date"}:
            return "simple"

        complex_indicators = (
            "step by step",
            "multiple",
            "analyze",
            "build",
            "create",
            "develop",
            "implement",
            "debug",
            "diagnose",
            "refactor",
            "modify",
            "patch",
            "fix",
            "project",
        )

        if any(
            indicator in normalized
            for indicator in complex_indicators
        ):
            return "complex"

        return "moderate"



request_analyzer = RequestAnalyzer()