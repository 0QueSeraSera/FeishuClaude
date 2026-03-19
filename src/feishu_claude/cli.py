"""CLI entry point for FeishuClaude."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .bot import FeishuClaudeBot
from .config import Settings


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="feishu-claude",
        description="Connect Feishu bot to local Claude Code CLI",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "-w", "--workspace",
        type=Path,
        default=Path("."),
        help="Working directory for Claude Code (default: current directory)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run startup checks and exit (don't start the bot)",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Load settings
    settings = Settings()

    # Validate Feishu config
    errors = settings.validate_feishu()
    if errors:
        logging.error("Configuration errors:")
        for err in errors:
            logging.error(f"  - {err}")
        logging.error("Please set required environment variables or create .env file")
        return 1

    if args.once:
        logging.info("Startup checks passed")
        return 0

    # Run the bot
    bot = FeishuClaudeBot(settings=settings, workspace=args.workspace)

    try:
        asyncio.run(bot.run_forever())
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        return 0
    except Exception as e:
        logging.error(f"Bot error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
