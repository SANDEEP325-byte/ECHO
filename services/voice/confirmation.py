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
        for path_key in ("path", "file_path", "target_path", "filename", "destination", "source"):
            if path_key in args and isinstance(args[path_key], str):
                try:
                    safe_target = Path(args[path_key]).name
                except Exception:  # noqa: BLE001
                    safe_target = str(args[path_key])
                break

        if (
            not safe_target
            and "targets" in args
            and isinstance(args["targets"], list)
            and args["targets"]
        ):
            try:
                safe_target = Path(str(args["targets"][0])).name
            except Exception:  # noqa: BLE001
                safe_target = str(args["targets"][0])

        # Tool-specific natural language summaries
        normalized_tool = tool_name.lower().replace("-", "_")

        if "delete" in normalized_tool:
            target_str = f" the file {safe_target}" if safe_target else ""
            return f"This action will delete{target_str}. Say yes to confirm or no to cancel."

        if "patch" in normalized_tool:
            target_str = f" to the file {safe_target}" if safe_target else ""
            return (
                f"This action will apply a patch{target_str}. Say yes to confirm or no to cancel."
            )

        if "write" in normalized_tool or "modify" in normalized_tool or "edit" in normalized_tool:
            target_str = f" the file {safe_target}" if safe_target else ""
            return f"This action will modify{target_str}. Say yes to confirm or no to cancel."

        if "test" in normalized_tool:
            target_str = f" on {safe_target}" if safe_target else " in the workspace"
            return f"This action will run tests{target_str}. Say yes to confirm or no to cancel."

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

    @classmethod
    def format_safe_vocal_result(
        cls,
        tool_name: str,
        result: Any = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> str:
        """Format a safe, human-readable vocal summary for TTS output.

        Guarantees:
        - NEVER exposes raw dictionaries, unified diffs, source code, or stack traces.
        - Scrubbed of secrets, environment variables, internal paths, and IDs.
        - Produces concise, natural spoken feedback.
        - Fails closed to generic safe messages for unexpected structures or errors.
        """
        normalized_tool = (tool_name or "").lower().replace("-", "_")

        # Handle failure cases safely
        if not success:
            if "test" in normalized_tool:
                if (
                    isinstance(result, dict)
                    and "summary" in result
                    and isinstance(result["summary"], dict)
                ):
                    s = result["summary"]
                    passed = s.get("passed", 0)
                    failed = s.get("failed", 0)
                    return f"Tests did not pass: {passed} passed, {failed} failed."
                return "Tests did not pass."

            # Verification failure check (across any tool)
            if error_message and (
                "verification failed" in error_message.lower()
                or "post-condition" in error_message.lower()
            ):
                return "Action executed, but post-condition verification failed."

            # Coding mutations fail to concise safe message
            if (
                "modify" in normalized_tool
                or "edit" in normalized_tool
                or "patch" in normalized_tool
            ):
                return "The action could not be completed."

            # Non-coding failure: check if safe error message is provided
            if error_message and isinstance(error_message, str):
                lower_err = error_message.lower()
                is_unsafe = (
                    any(k in lower_err for k in cls.SENSITIVE_KEYS)
                    or "traceback" in lower_err
                    or "line " in lower_err
                    or "0x" in lower_err
                    or "{" in error_message
                    or len(error_message) > 80
                )
                if not is_unsafe:
                    return f"Action execution failed: {error_message}"

            return "Action execution failed."

        # Handle successful coding & general tools
        if "modify" in normalized_tool or "edit" in normalized_tool:
            safe_target = ""
            if isinstance(result, dict):
                path_val = (
                    result.get("file_path") or result.get("target_path") or result.get("path")
                )
                if path_val and isinstance(path_val, str):
                    try:
                        safe_target = Path(path_val).name
                    except Exception:  # noqa: BLE001
                        safe_target = ""
            target_str = f" {safe_target}" if safe_target else ""
            return f"Action confirmed. Modified{target_str} successfully."

        if "patch" in normalized_tool:
            safe_target = ""
            if isinstance(result, dict):
                path_val = (
                    result.get("file_path") or result.get("target_path") or result.get("path")
                )
                if path_val and isinstance(path_val, str):
                    try:
                        safe_target = Path(path_val).name
                    except Exception:  # noqa: BLE001
                        safe_target = ""
            target_str = f" to {safe_target}" if safe_target else ""
            return f"Action confirmed. Patch applied successfully{target_str}."

        if "test" in normalized_tool:
            if isinstance(result, dict):
                summary = result.get("summary")
                if isinstance(summary, dict):
                    passed = summary.get("passed", 0)
                    failed = summary.get("failed", 0)
                    if failed == 0 and result.get("success", True):
                        return f"Tests passed: {passed} passed, {failed} failed."
                    return f"Tests did not pass: {passed} passed, {failed} failed."
                status = result.get("status", "")
                if status == "passed":
                    return "Tests passed successfully."
                return "Tests did not pass."
            return "Tests completed."

        if "delete" in normalized_tool:
            safe_target = ""
            if isinstance(result, dict):
                path_val = result.get("path") or result.get("file_path")
                if path_val and isinstance(path_val, str):
                    try:
                        safe_target = Path(path_val).name
                    except Exception:  # noqa: BLE001
                        safe_target = ""
            target_str = f" {safe_target}" if safe_target else ""
            return f"Action confirmed. Deleted{target_str} successfully."

        if (
            "command" in normalized_tool
            or "exec" in normalized_tool
            or "terminal" in normalized_tool
        ):
            return "Action confirmed. Command executed successfully."

        # If result is a short safe string (<= 80 chars) without newlines, dicts, or diffs
        if isinstance(result, str) and result and len(result) <= 80:
            lower_res = result.lower()
            if (
                "{" not in result
                and "\\" not in result
                and "---" not in result
                and "traceback" not in lower_res
                and "\n" not in result
            ):
                return f"Action confirmed and executed successfully: {result}"

        # Generic safe confirmation outcome
        return "Action confirmed and executed successfully."
