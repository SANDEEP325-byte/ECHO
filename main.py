"""Project ECHO — Main Entry Point (Phase 10A + 10B).

Unified bootstrap and runtime lifecycle launcher for ECHO.
Starts the interactive Rich CLI by default after running pre-flight diagnostics.

Usage:
  python main.py             Launch interactive CLI
  python main.py --status    Display system health diagnostics and exit
  python main.py --version   Display application version
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from apps.cli.app import CLIApp
from apps.cli.ui import render_status_table
from services.configuration.diagnostics import ComponentStatus, run_diagnostics
from services.configuration.lifecycle import lifecycle_manager
from services.configuration.settings import settings
from services.logging.logger import logger  # type: ignore[attr-defined]


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    """Parse command line launch arguments."""
    parser = argparse.ArgumentParser(
        prog="echo",
        description=f"{settings.app_name} — Personal AI Operating System (v{settings.app_version})",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Run pre-flight diagnostics, display system health report, and exit.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show application version and exit.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug console logging.",
    )
    return parser.parse_args(args_list)


async def async_main(args_list: list[str] | None = None) -> int:
    """Async main routine."""
    args = parse_args(args_list)

    if not args.debug:
        # Keep logs flowing to logs/echo.log, but keep console clean for Rich UI
        logger.remove()
        logger.add(
            "logs/echo.log",
            level="INFO",
            rotation="10 MB",
            retention="7 days",
            enqueue=True,
        )
        logger.add(
            sys.stderr,
            level="WARNING",
            enqueue=True,
        )

    if args.version:
        from rich.console import Console

        Console().print(
            f"[bold cyan]{settings.app_name}[/bold cyan] v{settings.app_version} ({settings.app_env})"
        )
        return 0

    # 1. Pre-Flight Diagnostics
    health = await run_diagnostics()

    if args.status:
        from rich.console import Console

        render_status_table(Console(), health)
        return 0 if health.is_runnable else 1

    # 2. Prevent startup if core components are BLOCKED
    if health.overall_status == ComponentStatus.BLOCKED:
        from rich.console import Console

        console = Console()
        console.print(
            "\n[bold red]ECHO Startup Blocked:[/bold red] Core system prerequisites failed.\n"
        )
        render_status_table(console, health)
        return 1

    # 3. Launch Interactive CLI
    cli_app = CLIApp(diagnostics=health)

    # Setup signal handlers for graceful shutdown on POSIX systems
    try:
        loop = asyncio.get_running_loop()
        for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if sig is not None and sys.platform != "win32":
                loop.add_signal_handler(
                    sig, lambda: asyncio.create_task(lifecycle_manager.shutdown())
                )
    except Exception:  # noqa: BLE001, S110
        pass

    try:
        await cli_app.run()
    finally:
        await lifecycle_manager.shutdown()

    return 0


def main() -> None:
    """Synchronous launcher entrypoint."""
    try:
        exit_code = asyncio.run(async_main())
        sys.exit(exit_code)
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        logger.critical("Fatal bootstrap error: {}", exc)
        print(f"\nFatal startup error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
