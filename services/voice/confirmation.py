"""Voice Confirmation & Safety Escalation (Phase 6E).

Provides strict, deterministic confirmation validation and safe human-readable
confirmation prompts for Project ECHO. Enforces zero fuzzy matching, zero LLM
guessing, and safe vocalization without exposing internal dictionaries, secrets,
or IDs.
"""

import re
from enum import Enum
from pathlib import Path
from typing import Any

from services.logging.logger import logger  # type: ignore[attr-defined]


class ConfirmationIntent(str, Enum):
    """Deterministic confirmation classification outcome."""

    CONFIRM = "confirm"
    CANCEL = "cancel"
    AMBIGUOUS = "ambiguous"


class VoiceConfirmationValidator:
    """Deterministic, closed-set voice confirmation parser and prompt generator."""

    # Mandatory Correction 1: Smallest deterministic closed-set
    ACCEPT_TOKENS: frozenset[str] = frozenset({"yes", "confirm", "okay", "lets go", "haan"})
    REJECT_TOKENS: frozenset[str] = frozenset({"no", "cancel", "naah"})

    # Sensitive argument keys that must NEVER be vocalized
    SENSITIVE_KEYS: frozenset[str] = frozenset(
        {
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "credential",
            "credentials",
            "private_key",
            "cookie",
            "headers",
        }
    )

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Normalize utterance by lowercasing and stripping punctuation and whitespace."""
        if not text:
            return ""
        # Remove punctuation characters
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        # Collapse multiple spaces into single space
        return " ".join(cleaned.split()).strip()

    @classmethod
    def validate(cls, utterance: str) -> ConfirmationIntent:
        """Deterministically validate confirmation intent without fuzzy matching.

        Enforces:
        - Exact match against ACCEPT_TOKENS -> CONFIRM
        - Exact match against REJECT_TOKENS -> CANCEL
        - Any other input -> AMBIGUOUS
        - Zero fuzzy matching, edit distance, semantic similarity, or regex wildcards.
        """
        cleaned = cls.normalize_text(utterance)
        if not cleaned:
            return ConfirmationIntent.AMBIGUOUS

        if cleaned in cls.ACCEPT_TOKENS:
            logger.info("Voice confirmation validated: CONFIRM (token='%s')", cleaned)
            return ConfirmationIntent.CONFIRM

        if cleaned in cls.REJECT_TOKENS:
            logger.info("Voice confirmation validated: CANCEL (token='%s')", cleaned)
            return ConfirmationIntent.CANCEL

        logger.warning(
            "Voice confirmation ambiguous: '%s' (not in accept or reject sets)", utterance
        )
        return ConfirmationIntent.AMBIGUOUS

    @classmethod
    def format_safe_prompt(
        cls,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Format a human-readable confirmation prompt without raw dicts, IDs, or secrets.

        Mandatory Correction 3:
        Do NOT vocalize raw internal PendingAction.arguments.
        Confirmation prompts must use a safe human-readable action summary and must
        not expose unnecessary sensitive/internal data.
        """
        args = arguments or {}
        safe_target = ""

        # Extract human-meaningful non-sensitive descriptor (e.g. filename)
        for path_key in ("path", "file_path", "filename", "destination", "source"):
            if path_key in args and isinstance(args[path_key], str):
                try:
                    safe_target = Path(args[path_key]).name
                except Exception:  # noqa: BLE001
                    safe_target = str(args[path_key])
                break

        # Tool-specific natural language summaries
        normalized_tool = tool_name.lower().replace("-", "_")

        if "delete" in normalized_tool:
            target_str = f" the file {safe_target}" if safe_target else ""
            return f"This action will delete{target_str}. Say yes to confirm or no to cancel."

        if "write" in normalized_tool or "modify" in normalized_tool or "edit" in normalized_tool:
            target_str = f" the file {safe_target}" if safe_target else ""
            return f"This action will modify{target_str}. Say yes to confirm or no to cancel."

        if (
            "command" in normalized_tool
            or "exec" in normalized_tool
            or "terminal" in normalized_tool
        ):
            cmd = args.get("command") or args.get("cmd") or ""
            # Don't vocalize huge commands or secrets
            if (
                cmd
                and len(str(cmd)) < 40
                and not any(k in str(cmd).lower() for k in cls.SENSITIVE_KEYS)
            ):
                return (
                    f"This action will run the command '{cmd}'. Say yes to confirm or no to cancel."
                )
            return "This action will execute a system command. Say yes to confirm or no to cancel."

        if "download" in normalized_tool:
            return "This action will download a file. Say yes to confirm or no to cancel."

        if "upload" in normalized_tool:
            return "This action will upload a file. Say yes to confirm or no to cancel."

        # Generic safe action summary
        human_name = normalized_tool.replace("_", " ")
        return f"This action will execute {human_name}. Say yes to confirm or no to cancel."
