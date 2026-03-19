"""Main bot logic that connects Feishu to Claude Code."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .claude_runner import ClaudeRunner, ClaudeSession
from .config import Settings, get_settings
from .feishu_adapter import FeishuAdapter, FeishuConfig, FeishuMessage

logger = logging.getLogger("feishu_claude")


class FeishuClaudeBot:
    """
    Main bot class that bridges Feishu messages to Claude Code CLI.

    Features:
    - Receives messages from Feishu via WebSocket
    - Routes messages to Claude Code CLI
    - Sends responses back to Feishu
    - Manages conversation sessions per chat
    """

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: Path | None = None,
    ):
        self.settings = settings or get_settings()
        self.workspace = workspace or self.settings.claude_workspace

        # Initialize components
        feishu_config = FeishuConfig.from_settings(self.settings)
        self.feishu = FeishuAdapter(feishu_config)
        self.claude = ClaudeRunner(
            workspace=self.workspace,
            model=self.settings.claude_model,
            max_turns=self.settings.claude_max_turns,
        )

        # Session management
        self._sessions: dict[str, ClaudeSession] = {}

        # Set up message handler
        self.feishu.set_message_handler(self._handle_message)

    async def start(self) -> None:
        """Start the bot."""
        # Validate configuration
        errors = self.settings.validate_feishu()
        if errors:
            raise ValueError("Configuration errors: " + "; ".join(errors))

        # Check Claude CLI availability
        available, info = ClaudeRunner.check_cli_available()
        if not available:
            raise RuntimeError(f"Claude Code CLI not available: {info}")
        logger.info(f"Claude Code CLI found at: {info}")

        # Start Feishu adapter
        await self.feishu.start()
        logger.info("FeishuClaude bot started")

    async def stop(self) -> None:
        """Stop the bot."""
        await self.feishu.stop()
        logger.info("FeishuClaude bot stopped")

    async def _handle_message(self, msg: FeishuMessage) -> None:
        """Process incoming Feishu message."""
        logger.info(f"Message from {msg.sender_id} in {msg.chat_id}: {msg.content[:50]}...")

        # Check for commands
        response = await self._process_command(msg)
        if response is not None:
            await self.feishu.send_message(msg.chat_id, response)
            return

        # Forward to Claude
        try:
            claude_response = await self.claude.send_message(
                chat_id=msg.chat_id,
                message=msg.content,
                continue_session=True,
            )

            if claude_response.is_error:
                logger.error(f"Claude error: {claude_response.content}")
                await self.feishu.send_message(
                    msg.chat_id,
                    f"❌ {claude_response.content}",
                )
            else:
                # Send Claude's response
                await self.feishu.send_message(msg.chat_id, claude_response.content)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await self.feishu.send_message(
                msg.chat_id,
                f"❌ Internal error: {e}",
            )

    async def _process_command(self, msg: FeishuMessage) -> str | None:
        """Process bot commands. Returns response or None if not a command."""
        content = msg.content.strip()
        tokens = content.split()
        if not tokens:
            return None

        cmd = tokens[0].lower()

        if cmd == "/help":
            return self._help_text()

        if cmd == "/new":
            self.claude.reset_session(msg.chat_id)
            return "✨ Started a new conversation session."

        if cmd == "/sessions":
            sessions = self.claude.list_sessions()
            if not sessions:
                return "No active sessions."
            lines = ["Active sessions:"]
            for sid in sessions:
                marker = "→ " if sid == msg.chat_id else "  "
                lines.append(f"{marker}{sid}")
            return "\n".join(lines)

        if cmd == "/status":
            available, info = ClaudeRunner.check_cli_available()
            status = "✅" if available else "❌"
            return (
                f"🤖 FeishuClaude Status\n"
                f"Claude CLI: {status} {info}\n"
                f"Workspace: {self.workspace}\n"
                f"Model: {self.settings.claude_model or 'default'}\n"
                f"Active sessions: {len(self.claude.list_sessions())}"
            )

        if cmd == "/ping":
            return "pong 🏓"

        # Not a command
        return None

    def _help_text(self) -> str:
        """Generate help text."""
        return (
            "🤖 FeishuClaude Bot Commands\n"
            "\n"
            "/help - Show this help\n"
            "/new - Start a new conversation\n"
            "/sessions - List active sessions\n"
            "/status - Show bot status\n"
            "/ping - Check if bot is responsive\n"
            "\n"
            "Just send a message to chat with Claude!"
        )

    async def run_forever(self) -> None:
        """Run the bot until interrupted."""
        await self.start()
        try:
            # Keep running until cancelled
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
