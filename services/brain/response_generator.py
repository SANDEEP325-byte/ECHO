from __future__ import annotations

import re
from typing import Any

from packages.interfaces.execution import ExecutionResult
from services.brain.intent_router import Intent
from services.memory.facts import fact_memory


class ResponseGenerator:
    """Centralized response generator for ECHO Brain.

    Adheres to ₹0 budget, security-first, and zero CoT/untrusted leakage principles.
    Formats deterministic responses, tool outputs, execution confirmations, and fallbacks.
    """

    def __init__(self, memory_manager: Any = None) -> None:
        self.memory_manager = memory_manager

    @staticmethod
    def _clean_memory_value(value: str) -> str:
        return value.strip().rstrip(".,!?;:")

    def generate_fixed_response(
        self,
        intent: Intent | str,
        memory_manager: Any = None,
    ) -> str | None:
        """Generate deterministic responses for identity or greetings."""
        mgr = memory_manager or self.memory_manager
        if mgr is not None:
            preferred_name = mgr.get_fact("preferred_name")
        else:
            preferred_name = fact_memory.get_fact("preferred_name")

        intent_obj = Intent(intent) if isinstance(intent, str) else intent

        if intent_obj == Intent.GREETING:
            if preferred_name:
                return (
                    f"Hello {preferred_name}! I'm ECHO, "
                    "your personal AI assistant. How can I help you today? 😊"
                )
            return "Hello! I'm ECHO, your personal AI assistant. How can I help you today? 😊"

        if intent_obj == Intent.IDENTITY:
            return "I'm ECHO, your personal AI assistant. 😌"

        return None

    def generate_memory_save_response(
        self,
        user_message: str,
        memory_manager: Any = None,
    ) -> str | None:
        """Parse and store facts from user message, returning confirmation string."""
        mgr = memory_manager or self.memory_manager
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
                name = self._clean_memory_value(match.group(1))
                if name:
                    if mgr is not None:
                        mgr.save_fact("name", name)
                    else:
                        fact_memory.save_fact("name", name)
                    return f"Got it! Your name is {name}. I'll remember that.😉"

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
                preferred_name = self._clean_memory_value(match.group(1))
                if preferred_name:
                    if mgr is not None:
                        mgr.save_fact("preferred_name", preferred_name)
                    else:
                        fact_memory.save_fact("preferred_name", preferred_name)
                    return f"Got it! I'll call you {preferred_name}. I'll remember that. 🫡"

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
                color = self._clean_memory_value(match.group(1))
                if color:
                    if mgr is not None:
                        mgr.save_fact("favorite_color", color)
                    else:
                        fact_memory.save_fact("favorite_color", color)
                    return f"Got it! Your favorite color is {color}. I'll remember that. 🫡"

        return None

    def generate_memory_recall_response(
        self,
        user_message: str,
        memory_manager: Any = None,
    ) -> str:
        """Retrieve facts from memory and format a readable response."""
        mgr = memory_manager or self.memory_manager
        normalized = user_message.lower().strip()

        if (
            "what is my name" in normalized
            or "what's my name" in normalized
            or "whats my name" in normalized
            or "do you know my name" in normalized
        ):
            if mgr is not None:
                value = mgr.get_fact("name")
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
            if mgr is not None:
                value = mgr.get_fact("preferred_name")
            else:
                value = fact_memory.get_fact("preferred_name")

            if value is not None:
                return f"I'll call you {value}. 😉"
            return "You haven't told me what you'd like me to call you yet."

        if "favorite color" in normalized or "favourite color" in normalized:
            if mgr is not None:
                value = mgr.get_fact("favorite_color")
            else:
                value = fact_memory.get_fact("favorite_color")

            if value is not None:
                return f"Your favorite color is {value}. 🫟"
            return "I don't know your favorite color yet."

        if mgr is not None:
            facts = mgr.get_all_facts()
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

    def generate_memory_delete_response(
        self,
        user_message: str,
        memory_manager: Any = None,
    ) -> str:
        """Delete specific or all facts from memory and format a confirmation response."""
        mgr = memory_manager or self.memory_manager
        normalized = user_message.lower().strip()

        if (
            "forget everything" in normalized
            or "forget all my memories" in normalized
            or "forget all my information" in normalized
        ):
            if mgr is not None:
                if hasattr(mgr, "clear_facts"):
                    mgr.clear_facts()
                elif hasattr(mgr, "clear"):
                    mgr.clear()
            else:
                fact_memory.clear()
            return "Okay, I've forgotten everything I remember about you."

        if "name" in normalized:
            if mgr is not None:
                mgr.delete_fact("name")
            else:
                fact_memory.delete_fact("name")
            return "Okay, I've forgotten your name."

        if "favorite color" in normalized or "favourite color" in normalized:
            if mgr is not None:
                mgr.delete_fact("favorite_color")
            else:
                fact_memory.delete_fact("favorite_color")
            return "Okay, I've forgotten your favorite color."

        if "call me" in normalized or "preferred name" in normalized:
            if mgr is not None:
                mgr.delete_fact("preferred_name")
            else:
                fact_memory.delete_fact("preferred_name")
            return "Okay, I've forgotten what you'd like me to call you."

        return "I don't know which memory you want me to forget."

    def generate_tool_response(
        self,
        intent: Intent | str,
        tool_result: Any,
    ) -> str:
        """Format the output of single tool executions into clean user-facing responses."""
        try:
            intent_obj = Intent(intent) if isinstance(intent, str) else intent
        except ValueError:
            intent_obj = None

        if intent_obj == Intent.CALCULATOR:
            return f"The result is {tool_result}."
        if intent_obj == Intent.TIME:
            return f"The current time is {tool_result}."
        if intent_obj == Intent.DATE:
            return f"Today's date is {tool_result}."
        return str(tool_result)

    def generate_confirmation_prompt(
        self,
        pending_action: dict[str, Any] | None,
    ) -> str:
        """Format an explicit, structured confirmation prompt for human-in-the-loop authorization."""
        if not pending_action:
            return "This action requires confirmation before proceeding. Would you like to proceed? (yes/no)"

        tool = pending_action.get("tool", "unknown_operation")
        args = pending_action.get("arguments", {})

        if tool == "run_tests":
            framework = str(args.get("framework", "pytest"))
            raw_targets = args.get("targets")
            if isinstance(raw_targets, (list, tuple)):
                targets_str = ", ".join(str(t) for t in raw_targets[:3])
                if len(raw_targets) > 3:
                    targets_str += f" and {len(raw_targets) - 3} more"
            elif raw_targets:
                targets_str = str(raw_targets)
            else:
                targets_str = "entire suite"
            timeout = args.get("timeout", 30.0)
            return (
                f"This action requires confirmation: execute {framework} tests on {targets_str} "
                f"(timeout {timeout}s). Would you like to proceed? (yes/no)"
            )

        if "." in tool:
            from services.plugins.security_policy import PluginSecurityPolicy

            plugin_id, tool_name = tool.split(".", 1)
            safe_args = PluginSecurityPolicy.redact_arguments(args) if args else {}
            args_str = f" with arguments {safe_args}" if safe_args else ""
            return (
                f"This action requires confirmation from plugin '{plugin_id}': execute tool '{tool_name}'{args_str}. "
                "Would you like to proceed? (yes/no)"
            )

        args_str = f" with arguments {args}" if args else ""
        return (
            f"This action requires confirmation: '{tool}'{args_str}. "
            "Would you like to proceed? (yes/no)"
        )

    def generate_execution_response(
        self,
        execution_result: ExecutionResult,
        verification_result: Any = None,
    ) -> str:
        """Generate response from plan execution, handling confirmations and errors."""
        if execution_result.requires_confirmation:
            return self.generate_confirmation_prompt(execution_result.pending_action)

        if not execution_result.success:
            return execution_result.error or "I couldn't complete the execution."

        if verification_result is not None and not verification_result.success:
            return verification_result.error or "Execution verification failed."

        return str(execution_result.result)

    def generate_fallback_response(
        self,
        error: str | None = None,
    ) -> str:
        """Safe fallback response on component failure with no technical leakage."""
        return "I couldn't process your request because an internal component failed."


response_generator = ResponseGenerator()
