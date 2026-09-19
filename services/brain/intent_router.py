import re
from enum import Enum
from services.brain.tool_router import tool_router

class Intent(str, Enum):
    GREETING = "greeting"
    IDENTITY = "identity"
    TIME= "time"
    DATE= "date"
    CALCULATOR= "calculator"
    MEMORY_SAVE = "memory_save"
    MEMORY_RECALL = "memory_recall"
    MEMORY_DELETE = "memory_delete"
    CODING = "coding"
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
        r"^what is your name$",
        r"^what's your name$",
        r"^whats your name$",
        r"^tell me your name$",
        r"^what is your identity$",
    ]
    
    TIME_PATTERNS = [
        r"^what time is it$",
        r"^what's the time$",
        r"^whats the time$",
        r"^tell me the time$",
        r"^current time$",
        r"^what is the current time$",
        r"^what's the current time$",
        r"^whats the current time$",
    ]
    
    DATE_PATTERNS = [
        r"^what is today's date$",
        r"^what's today's date$",
        r"^whats today's date$",
        r"^what is the date today$",
        r"^what's the date today$",
        r"^whats the date today$",
        r"^what date is it$",
        r"^tell me today's date$",
        r"^tell me the date today$",
    ]
    
    MEMORY_SAVE_PATTERNS = [
        r"^my name is .+$",
        r"^i'm .+$",
        r"^i am .+$",
        r"^call me .+$",
        r"^you can call me .+$",
        r"^actually, call me .+$",
        r"^(actually, )?call me .+$",
        r"^my favorite color is .+$",
        r"^my favourite color is .+$",
        
        r"^no, my name is .+$",
        r"^no my name is .+$",

        r"^i actually prefer to be called .+$",

        r"^from now on, call me .+$",
        r"^from now on call me .+$",

        r"^my favorite color is actually .+$",
        r"^my favourite color is actually .+$",

        r"^actually, my name is .+$",
        r"^actually my name is .+$",
        r"^actually, call me .+$",
        r"^actually call me .+$",
        r"^actually, you can call me .+$",
        r"^actually you can call me .+$",
        r"^actually, my favorite color is .+$",
        r"^actually my favorite color is .+$",
        r"^actually, my favourite color is .+$",
        r"^actually my favourite color is .+$",
    ]
    
    MEMORY_RECALL_PATTERNS = [
        # Name
        r"^what is my name$",
        r"^what's my name$",
        r"^whats my name$",
        r"^do you know my name$",
        
        # Preferred Name
        r"^what should you call me$",
        r"^what do you call me$",
        r"^what is my preferred name$",
        r"^what's my preferred name$",
        r"^what name should you use$",

        # Favorite color
        r"^what is my favorite color$",
        r"^what's my favorite color$",
        r"^whats my favorite color$",
        r"^do you know my favorite color$",
        r"^what is my favourite color$",
        r"^what's my favourite color$",
        r"^whats my favourite color$",
        r"^do you know my favourite color$",

        # General memory recall
        r"^tell me something about myself$",
        r"^tell me what you remember about me$",
        r"^what do you remember about me$",
        r"^what do you remember$",
        r"^what do you know about me$",
        r"^tell me what you know about me$",
    ]
    
    MEMORY_DELETE_PATTERN = [
        r"^forget my name$",
        r"^forget what you call me$",
        r"^forget my favorite color$",
        r"^forget my favourite color$",
        r"^forget everything$",
        r"^forget everything you know about me$",
        r"^forget everything you remember about me$",
        r"^forget all my memories$",
        r"^forget all my information$",
        
    ]
    
    def classify(self, message: str) -> Intent:
        normalized = self._normalize(message)
        
        if self._matches(normalized, self.GREETING_PATTERNS):
            return Intent.GREETING
        
        if self._matches(normalized, self.IDENTITY_PATTERNS):
            return Intent.IDENTITY
        
        if self._matches(normalized, self.TIME_PATTERNS):
            return Intent.TIME
        
        if self._matches(normalized, self.DATE_PATTERNS):
            return Intent.DATE
        
        if self._matches(normalized, self.MEMORY_RECALL_PATTERNS):
            return Intent.MEMORY_RECALL
        
        if self._matches(normalized, self.MEMORY_DELETE_PATTERN):
            return Intent.MEMORY_DELETE
        
        if self._matches(normalized, self.MEMORY_SAVE_PATTERNS):
            return Intent.MEMORY_SAVE
        
        if tool_router.should_use_calculator(normalized):
            return Intent.CALCULATOR

        from services.coding.cognition import coding_cognition

        is_coding, _, _ = coding_cognition.classify_coding_intent(normalized)
        if is_coding:
            return Intent.CODING

        return Intent.GENERAL

    
    @staticmethod
    def _normalize(message: str) -> str:
        message = message.strip().lower()
        message = re.sub(r"\s+", " ", message)
        message = re.sub(r"[.!?]+$", "", message)
        return message
    
    @staticmethod
    def _matches(message: str, patterns: list[str]) -> bool:
        return any(
            re.fullmatch(pattern, message, re.IGNORECASE)
            for pattern in patterns
        )
        
intent_router = IntentRouter()