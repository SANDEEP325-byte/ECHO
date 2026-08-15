import re
from enum import Enum

class Intent(str, Enum):
    GREETING = "greeting"
    IDENTITY = "identity"
    CALCULATOR= "calculator"
    GENERAL = "general"
    
class IntentRouter:
    """Classifies simple user request before they reach the AI model."""
    
    GREETING_PATTERNS = [
        r"^hello$",
        r"^hello echo$",
        r"^hi$",
        r"^hi echo$",
        r"^hey$",
        r"^hey echo$",
        r"^good morning$",
        r"^good afternoon$",
        r"^good evening$",
    ]
    
    IDENTITY_PATTERNS = [
        r"^who are you$",
        r"^who am i talking to$",
        r"^who am i talking to\?$",
        r"^what is your name$",
        r"^what is your name\?$",
        r"^what's your name$",
        r"^what's your name\?$",
        r"^whats your name$",
        r"^whats your name\?$",
        r"^tell me your name$",
        r"^what is your identity$",
    ]
    
    def classify(self, message: str) -> Intent:
        normalized = self._normalize(message)
        
        if self._matches(normalized, self.GREETING_PATTERNS):
            return Intent.GREETING
        
        if self._matches(normalized, self.IDENTITY_PATTERNS):
            return Intent.IDENTITY
        
        return Intent.GENERAL
    
    @staticmethod
    def _normalize(message: str) -> str:
        message = message.strip().lower()
        message = re.sub(r"\s+", " ", message)
        message = re.sub(r"[!?]+$", "", message)
        return message
    
    @staticmethod
    def _matches(message: str, patterns: list[str]) -> bool:
        return any(
            re.fullmatch(pattern, message, re.IGNORECASE)
            for pattern in patterns
        )
        
intent_router = IntentRouter()