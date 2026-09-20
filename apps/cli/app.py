"""Interactive CLI Application Engine (Phase 10B).

Coordinates interactive user conversation, slash commands, session management,
and human-in-the-loop confirmation UX for Project ECHO.

Architectural Guarantees:
- Interface Layer only: Communicates exclusively with ECHOBrain.
- Never invokes tools directly, reasons independently, or bypasses SafetyEngine.
- Preserves session ID across sequential turns.
- Enforces strict confirmation input handling.
- Graceful termination on Ctrl+C (KeyboardInterrupt) or EOFError without tracebacks.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from rich.console import Console

from apps.cli.ui import (
    render_assistant_turn,
    render_banner,
    render_confirmation_card,
    render_error,
    render_help,
    render_info,
    render_memory_view,
    render_status_table,
)
from packages.interfaces.request import Request
from services.brain.brain import ECHOBrain, echo_brain
from services.configuration.diagnostics import SystemHealth, run_diagnostics
from services.logging.logger import logger  # type: ignore[attr-defined]


class CLIApp:
    """Interactive command-line interface for ECHO."""

    def __init__(
        self,
        brain: ECHOBrain | None = None,
        console: Console | None = None,
        session_id: str | None = None,
        diagnostics: SystemHealth | None = None,
        input_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.brain: ECHOBrain = brain or echo_brain
        self.console: Console = console or Console()
        self.session_id: str = session_id or f"cli_{uuid.uuid4().hex[:8]}"
        self.diagnostics: SystemHealth | None = diagnostics
        self.input_fn: Callable[[str], str] = input_fn or input
        self.active_pending_id: str | None = None
        self.running: bool = True

    async def run(self) -> None:
        """Run the interactive conversational loop."""
        render_banner(self.console, self.diagnostics)

        while self.running:
            try:
                # Prompt user for input
                raw_input = self._read_input("You > ")
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[italic dim]Exiting ECHO... Goodbye![/italic dim]\n")
                self.running = False
                break

            user_text = raw_input.strip()

            # 1. Empty input must not trigger Brain request
            if not user_text:
                continue

            # 2. Handle slash commands
            if user_text.startswith("/"):
                await self._handle_slash_command(user_text)
                continue

            # 3. Handle active pending confirmation
            if self.active_pending_id is not None:
                handled = await self._handle_confirmation_response(user_text)
                if handled:
                    continue

            # 4. Standard conversational / tool request dispatch
            await self._process_user_message(user_text)

    def _read_input(self, prompt_text: str) -> str:
        """Read a single line of input using the configured input callable."""
        # Use rich formatting for prompt string if using standard console
        return self.input_fn(prompt_text)

    async def _handle_slash_command(self, command_str: str) -> None:
        """Process local slash commands."""
        parts = command_str.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            self.console.print("[italic dim]Exiting ECHO... Goodbye![/italic dim]\n")
            self.running = False
            return

        if cmd == "/help":
            render_help(self.console)
            return

        if cmd == "/status":
            health = await run_diagnostics()
            render_status_table(self.console, health)
            return

        if cmd == "/memory":
            await self._display_memory()
            return

        if cmd == "/confirm":
            target_id = arg or self.active_pending_id
            if not target_id:
                render_error(self.console, "No action ID specified or pending to confirm.")
                return
            await self._execute_confirmation(target_id)
            return

        if cmd == "/cancel":
            target_id = arg or self.active_pending_id
            if not target_id:
                render_error(self.console, "No action ID specified or pending to cancel.")
                return
            await self._execute_cancellation(target_id)
            return

        render_error(
            self.console,
            f"Unknown command '{cmd}'. Type [bold cyan]/help[/bold cyan] for available commands.",
        )

    async def _handle_confirmation_response(self, user_text: str) -> bool:
        """Evaluate strict yes/no confirmation response for an active pending action."""
        normalized = user_text.lower()
        target_id = self.active_pending_id
        if not target_id:
            return False

        if normalized in ("yes", "y", "confirm", "approve"):
            self.active_pending_id = None
            await self._execute_confirmation(target_id)
            return True

        if normalized in ("no", "n", "cancel", "reject", "abort"):
            self.active_pending_id = None
            await self._execute_cancellation(target_id)
            return True

        # Non-confirmation input while pending action exists
        render_error(
            self.console,
            f"Action '{target_id}' is pending authorization. "
            "Please respond strictly with 'yes' to approve, 'no' to reject, or type /cancel.",
        )
        return True

    async def _execute_confirmation(self, action_id: str) -> None:
        """Confirm action through authoritative ECHOBrain confirmation API."""
        try:
            res = self.brain.confirm_action(action_id, session_id=self.session_id)
            if res.success:
                render_assistant_turn(
                    self.console,
                    f"Action '{action_id}' confirmed and executed successfully: {res.result}",
                )
            else:
                render_error(self.console, f"Action confirmation failed: {res.message}")
        except Exception as exc:  # noqa: BLE001
            logger.error("Confirmation error: {}", exc)
            render_error(self.console, f"Action confirmation encountered an error: {exc}")
        finally:
            if self.active_pending_id == action_id:
                self.active_pending_id = None

    async def _execute_cancellation(self, action_id: str) -> None:
        """Cancel action through authoritative ECHOBrain cancellation API."""
        try:
            res = self.brain.cancel_action(action_id, session_id=self.session_id)
            if res.success:
                render_assistant_turn(
                    self.console,
                    f"Action '{action_id}' has been cancelled.",
                )
            else:
                render_error(self.console, f"Action cancellation failed: {res.message}")
        except Exception as exc:  # noqa: BLE001
            logger.error("Cancellation error: {}", exc)
            render_error(self.console, f"Action cancellation encountered an error: {exc}")
        finally:
            if self.active_pending_id == action_id:
                self.active_pending_id = None

    async def _display_memory(self) -> None:
        """Retrieve and format memory contents via safe MemoryManager APIs."""
        if not self.brain.memory_manager:
            render_info(self.console, "MemoryManager is not active in this environment.")
            return

        try:
            facts = self.brain.memory_manager.get_all_facts()
            recent_msgs = self.brain.memory_manager.get_recent_messages(limit=10)
            render_memory_view(self.console, facts=facts, recent_messages=recent_msgs)
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory display failed: {}", exc)
            render_error(self.console, f"Failed to retrieve memory snapshot: {exc}")

    async def _process_user_message(self, message: str) -> None:
        """Dispatch user message into canonical Request -> ECHOBrain pipeline."""
        req = Request(
            user_input=message,
            source="cli",
            session_id=self.session_id,
        )

        try:
            response_text = await self.brain.process(req)
        except Exception as exc:  # noqa: BLE001
            logger.error("Brain processing error: {}", exc)
            render_error(
                self.console,
                "An internal component failed to process your request. Please try again.",
            )
            return

        # Check if the execution halted because an action requires confirmation
        requires_confirm = bool(
            req.context.get("requires_confirmation")
            or (
                hasattr(req, "result")
                and req.result
                and getattr(req.result, "requires_confirmation", False)
            )
        )

        if requires_confirm:
            pending_id = req.context.get("pending_action_id")
            pending_act = getattr(req.result, "pending_action", None) if req.result else None
            if not pending_id and isinstance(pending_act, dict):
                pending_id = pending_act.get("action_id")

            self.active_pending_id = pending_id

            tool_name = (
                pending_act.get("tool", "Action")
                if isinstance(pending_act, dict)
                else "Sensitive Operation"
            )
            risk_level = (
                str(pending_act.get("risk_level", "SENSITIVE"))
                if isinstance(pending_act, dict)
                else "SENSITIVE"
            )
            args = pending_act.get("arguments", {}) if isinstance(pending_act, dict) else {}

            render_confirmation_card(
                self.console,
                action_id=pending_id or "pending",
                tool=tool_name,
                risk_level=risk_level,
                arguments=args,
                prompt_text=response_text,
            )
        else:
            self.active_pending_id = None
            render_assistant_turn(self.console, response_text)
