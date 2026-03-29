"""Main bot logic that connects Feishu to Claude Code."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from .claude_runner import ClaudeRunner
from .config import Settings, get_settings
from .codex_runner import CodexRunner, ExecutionMode, MODE_FLAG_MAP
from .feishu_adapter import FeishuAdapter, FeishuConfig, FeishuMessage
from .runtime_state import BackendType, ChatRuntimeState

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
        self.codex = CodexRunner(
            workspace=self.settings.effective_codex_workspace,
            model=self.settings.codex_model,
            search_enabled=self.settings.codex_search_enabled,
            mode=self.settings.codex_default_mode,
        )
        self.backend: BackendType = self.settings.feishu_backend

        # Per-chat runtime state
        self._chat_states: dict[str, ChatRuntimeState] = {}

        # Set up message handler
        self.feishu.set_message_handler(self._handle_message)

    async def start(self) -> None:
        """Start the bot."""
        # Validate configuration
        errors = self.settings.validate_feishu()
        if errors:
            raise ValueError("Configuration errors: " + "; ".join(errors))

        runner_name, runner = self._backend_runner(self.backend)
        available, info = runner.check_cli_available()
        if not available:
            raise RuntimeError(f"{runner_name} CLI not available: {info}")
        logger.info(f"{runner_name} CLI found at: {info}")

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

        state = self._chat_state(msg.chat_id)

        try:
            _, runner = self._backend_runner(state.backend)
            if state.backend == "codex":
                backend_response = await self.codex.send_message(
                    chat_id=msg.chat_id,
                    message=msg.content,
                    continue_session=True,
                    mode=state.mode,
                    model=state.effective_model(self.settings.codex_model),
                    search_enabled=state.search_enabled,
                )
            else:
                session = self.claude.get_or_create_session(msg.chat_id)
                session.model = state.effective_model(self.settings.claude_model)
                backend_response = await self.claude.send_message(
                    chat_id=msg.chat_id,
                    message=msg.content,
                    continue_session=True,
                )

            if backend_response.is_error:
                logger.error(f"Runner error: {backend_response.content}")
                await self.feishu.send_message(
                    msg.chat_id,
                    f"❌ {backend_response.content}",
                )
            else:
                # Send backend response
                await self.feishu.send_message(msg.chat_id, backend_response.content)

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
        state = self._chat_state(msg.chat_id)

        if cmd == "/help":
            return self._help_text()

        if cmd == "/new":
            _, runner = self._backend_runner(state.backend)
            runner.reset_session(msg.chat_id)
            return "✨ Started a new conversation session."

        if cmd == "/sessions":
            _, runner = self._backend_runner(state.backend)
            sessions = runner.list_sessions()
            if not sessions:
                return "No active sessions."
            lines = ["Active sessions:"]
            for sid in sessions:
                marker = "→ " if sid == msg.chat_id else "  "
                lines.append(f"{marker}{sid}")
            return "\n".join(lines)

        if cmd == "/mode":
            return self._handle_mode_command(tokens, state)

        if cmd == "/model":
            return self._handle_model_command(tokens, state)

        if cmd == "/search":
            return self._handle_search_command(tokens, state)

        if cmd == "/tools":
            return self._tools_text(state)

        if cmd == "/status":
            runner_name, runner = self._backend_runner(state.backend)
            available, info = runner.check_cli_available()
            status = "✅" if available else "❌"
            return (
                f"🤖 FeishuClaude Status\n"
                f"Backend: {state.backend}\n"
                f"Mode: {state.mode}\n"
                f"Search: {'on' if state.search_enabled else 'off'}\n"
                f"{runner_name} CLI: {status} {info}\n"
                f"Workspace: {self._current_workspace(state.backend)}\n"
                f"Model: {self._current_model_name(state)}\n"
                f"Active sessions: {len(runner.list_sessions())}"
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
            "/mode <safe|normal|full> - Set Codex execution mode\n"
            "/model <name|default> - Set per-chat model override\n"
            "/search <on|off> - Toggle Codex web search\n"
            "/tools - Show effective safety controls\n"
            "/status - Show bot status\n"
            "/ping - Check if bot is responsive\n"
            "\n"
            "Just send a message to chat with the configured backend!"
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

    def _backend_runner(
        self,
        backend: BackendType,
    ) -> tuple[str, ClaudeRunner | CodexRunner]:
        """Get backend runner by backend id.

        Returns:
            Tuple of display name and runner instance.
        """
        if backend == "codex":
            return "Codex", self.codex
        return "Claude", self.claude

    def _chat_state(self, chat_id: str) -> ChatRuntimeState:
        """Get or initialize runtime state for a chat."""
        if chat_id not in self._chat_states:
            self._chat_states[chat_id] = ChatRuntimeState(
                backend=self.backend,
                mode=self.settings.codex_default_mode,
                search_enabled=self.settings.codex_search_enabled,
            )
        return self._chat_states[chat_id]

    def _current_model_name(self, state: ChatRuntimeState) -> str:
        """Get model name for status output."""
        if state.backend == "codex":
            return state.effective_model(self.settings.codex_model) or "default"
        return state.effective_model(self.settings.claude_model) or "default"

    def _current_workspace(self, backend: BackendType) -> Path:
        """Get workspace path for selected backend."""
        if backend == "codex":
            return self.settings.effective_codex_workspace
        return self.workspace

    def _handle_mode_command(self, tokens: list[str], state: ChatRuntimeState) -> str:
        """Handle `/mode` command parsing and state update."""
        if len(tokens) != 2:
            return "Usage: /mode <safe|normal|full>"
        value = tokens[1].strip().lower()
        if value not in {"safe", "normal", "full"}:
            return "Invalid mode. Use /mode <safe|normal|full>."
        mode = value  # type: ignore[assignment]
        state.mode = mode
        warning = ""
        if mode == "full":
            warning = "\n⚠️ full mode bypasses approvals and sandbox."
        return f"Mode set to `{mode}`.{warning}"

    def _handle_model_command(self, tokens: list[str], state: ChatRuntimeState) -> str:
        """Handle `/model` command parsing and state update."""
        if len(tokens) != 2:
            return "Usage: /model <name|default>"
        model = tokens[1].strip()
        if model.lower() in {"default", "none", "reset"}:
            state.model = None
            return "Model override cleared. Using backend default."
        state.model = model
        return f"Model override set to `{model}`."

    def _handle_search_command(self, tokens: list[str], state: ChatRuntimeState) -> str:
        """Handle `/search` command parsing and state update."""
        if len(tokens) != 2:
            return "Usage: /search <on|off>"
        value = tokens[1].strip().lower()
        if value == "on":
            state.search_enabled = True
            return "Search enabled for this chat."
        if value == "off":
            state.search_enabled = False
            return "Search disabled for this chat."
        return "Invalid value. Use /search <on|off>."

    def _tools_text(self, state: ChatRuntimeState) -> str:
        """Return chat-scoped safety control snapshot."""
        if state.backend != "codex":
            return (
                "Tools snapshot\n"
                "Backend: claude\n"
                "Codex safety controls are available after switching backend to codex."
            )

        flags = " ".join(MODE_FLAG_MAP[state.mode])
        return (
            "Tools snapshot\n"
            f"Backend: codex\n"
            f"Mode: {state.mode}\n"
            f"Flags: {flags}\n"
            f"Search: {'on' if state.search_enabled else 'off'}\n"
            f"Model: {state.model or self.settings.codex_model or 'default'}"
        )
