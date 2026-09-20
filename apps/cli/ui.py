"""Rich UI Components for ECHO CLI (Phase 10B).

Implements beautiful, terminal-native visual components using the Rich library:
- Modern startup banner with system readiness indicators
- Formatted markdown response rendering
- Human-in-the-loop Action Confirmation Cards with risk coloring
- Bounded memory inspection views
- System health diagnostic tables
- Command help menus
"""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from services.configuration.diagnostics import ComponentStatus, SystemHealth
from services.configuration.settings import settings
from services.plugins.security_policy import PluginSecurityPolicy


def render_banner(console: Console, health: SystemHealth | None = None) -> None:
    """Render the startup banner with concise readiness status."""
    title_text = Text()
    title_text.append(f"{settings.app_name} ", style="bold cyan")
    title_text.append(f"v{settings.app_version}\n", style="bold white")
    title_text.append("Personal AI Operating System\n", style="italic")
    title_text.append("Privacy-First • Local-First • Offline • ₹0 Budget\n\n", style="dim")

    if health is not None:
        if health.overall_status == ComponentStatus.READY:
            status_style = "bold green"
            status_desc = "READY (All subsystems operational)"
        elif health.overall_status == ComponentStatus.DEGRADED:
            status_style = "bold yellow"
            status_desc = "DEGRADED (Local Ollama or voice unavailable; fallback mode active)"
        else:
            status_style = "bold red"
            status_desc = "BLOCKED (Core requirements missing)"

        title_text.append("Status: ", style="bold")
        title_text.append(f"[{health.overall_status.value}] ", style=status_style)
        title_text.append(status_desc, style="dim")
    else:
        title_text.append("Status: [READY]", style="bold green")

    panel = Panel(
        title_text,
        box=box.ROUNDED,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)
    console.print(
        "[dim]Type your message to chat, or [/dim][bold cyan]/help[/bold cyan][dim] for commands. Press Ctrl+C or type [/dim][bold cyan]/exit[/bold cyan][dim] to quit.[/dim]\n"
    )


def render_assistant_turn(console: Console, response_text: str) -> None:
    """Render the assistant response cleanly using markdown where appropriate."""
    console.print("\n[bold green]ECHO >[/bold green]")
    try:
        # Attempt rich markdown rendering
        md = Markdown(response_text)
        console.print(md)
    except Exception:  # noqa: BLE001
        # Fallback to plain text if markdown parsing fails
        console.print(response_text)
    console.print("")


def render_confirmation_card(
    console: Console,
    action_id: str,
    tool: str,
    risk_level: str,
    arguments: dict[str, Any],
    prompt_text: str | None = None,
) -> None:
    """Render an authoritative, un-missable confirmation prompt for sensitive actions."""
    is_critical = "critical" in risk_level.lower()
    border_color = "red" if is_critical else "yellow"

    content = Text()
    content.append("⚠️  SENSITIVE ACTION REQUIRES AUTHORIZATION\n\n", style=f"bold {border_color}")

    content.append("Operation:  ", style="bold white")
    content.append(f"{tool}\n", style="bold cyan")

    content.append("Risk Level: ", style="bold white")
    badge_style = "bold red" if is_critical else "bold yellow"
    content.append(f"[{risk_level.upper()}]\n", style=badge_style)

    content.append("Action ID:  ", style="bold white")
    content.append(f"{action_id}\n\n", style="dim")

    # Display safe, redacted arguments
    if arguments:
        safe_args = PluginSecurityPolicy.redact_arguments(arguments)
        content.append("Target / Parameters:\n", style="bold white")
        for k, v in safe_args.items():
            content.append(f"  • {k}: ", style="cyan")
            content.append(f"{v}\n", style="white")
        content.append("\n")

    if prompt_text:
        content.append(f"Details: {prompt_text}\n\n", style="italic dim")

    content.append("─" * 45 + "\n", style="dim")
    content.append("Approve: ", style="bold green")
    content.append("Type 'yes' (or /confirm)   ", style="green")
    content.append("Reject: ", style="bold red")
    content.append("Type 'no' (or /cancel)", style="red")

    panel = Panel(
        content,
        title=f"[bold {border_color}]Confirmation Required[/bold {border_color}]",
        box=box.HEAVY,
        border_style=border_color,
        padding=(1, 2),
    )
    console.print(panel)


def render_status_table(console: Console, health: SystemHealth) -> None:
    """Render a structured table of system diagnostics."""
    table = Table(
        title="ECHO System Diagnostics",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Subsystem", style="bold white", width=22)
    table.add_column("Type", width=10)
    table.add_column("Status", width=12, justify="center")
    table.add_column("Diagnostic Output", style="white")

    for check in health.checks:
        type_str = "Core" if check.is_core else "Optional"
        if check.status == ComponentStatus.READY:
            status_text = Text("[READY]", style="bold green")
        elif check.status == ComponentStatus.DEGRADED:
            status_text = Text("[DEGRADED]", style="bold yellow")
        else:
            status_text = Text("[BLOCKED]", style="bold red")

        table.add_row(check.name, type_str, status_text, check.message)

    console.print("\n", table)
    summary_color = "green" if health.is_runnable else "red"
    console.print(
        f"Overall System State: [bold {summary_color}]{health.overall_status.value}[/bold {summary_color}] "
        f"({'Operational' if health.is_runnable else 'Halted - Core Prerequisites Failed'})\n"
    )


def render_memory_view(
    console: Console,
    facts: dict[str, str],
    recent_messages: list[dict[str, str]],
) -> None:
    """Render a bounded, human-readable view of stored facts and conversation context."""
    console.print("\n[bold cyan]─── ECHO Memory Snapshot ───[/bold cyan]\n")

    # Facts Table
    if facts:
        facts_table = Table(
            title=f"Stored Facts ({len(facts)})",
            box=box.SIMPLE_HEAVY,
            header_style="bold yellow",
        )
        facts_table.add_column("Key", style="bold white", width=25)
        facts_table.add_column("Value", style="cyan")

        # Cap display at 20 items to prevent flooding
        for k, v in list(facts.items())[:20]:
            val_snippet = (v[:75] + "...") if len(v) > 75 else v
            facts_table.add_row(k, val_snippet)

        console.print(facts_table)
    else:
        console.print("[dim]No long-term facts stored yet.[/dim]\n")

    # Recent Conversation History
    if recent_messages:
        hist_table = Table(
            title=f"Recent Conversation History ({len(recent_messages)} turns)",
            box=box.SIMPLE_HEAVY,
            header_style="bold green",
        )
        hist_table.add_column("Role", style="bold white", width=12)
        hist_table.add_column("Message Preview", style="white")

        for msg in recent_messages[-8:]:
            role = msg.get("role", "unknown").capitalize()
            role_style = "green" if role.lower() == "assistant" else "cyan"
            content = msg.get("content", "")
            preview = (content[:80] + "...") if len(content) > 80 else content
            hist_table.add_row(Text(role, style=role_style), preview)

        console.print(hist_table)
    else:
        console.print("[dim]No previous conversation turns recorded.[/dim]\n")


def render_help(console: Console) -> None:
    """Render the command assistance menu."""
    table = Table(
        title="Available ECHO Commands",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Command", style="bold yellow", width=22)
    table.add_column("Description", style="white")

    table.add_row("/help", "Show this help and command reference.")
    table.add_row("/status", "Display local system diagnostics and component readiness.")
    table.add_row("/memory", "Inspect stored long-term facts and recent conversation turns.")
    table.add_row("/confirm <id>", "Explicitly approve and resume a pending sensitive action.")
    table.add_row("/cancel <id>", "Explicitly reject and cancel a pending sensitive action.")
    table.add_row("/exit, /quit", "Gracefully terminate the ECHO session.")

    console.print("\n", table)
    console.print(
        "[dim]To chat, simply type normal text at the prompt without a leading slash.[/dim]\n"
    )


def render_error(console: Console, message: str) -> None:
    """Render a clean error message without leaking stack traces."""
    console.print(f"[bold red]Error:[/bold red] {message}\n")


def render_info(console: Console, message: str) -> None:
    """Render an informational notice."""
    console.print(f"[italic dim]{message}[/italic dim]\n")
