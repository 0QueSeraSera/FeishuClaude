"""Main bot logic that connects Feishu to Claude/Codex backends."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from .claude_runner import ClaudeRunner, ClaudeResponse
from .config import Settings, get_settings
from .codex_runner import CodexEventSummary, CodexRunner, MODE_FLAG_MAP
from .feishu_adapter import FeishuAdapter, FeishuConfig, FeishuMessage
from .runtime_state import BackendType, ChatRuntimeState

logger = logging.getLogger("feishu_claude")


class FeishuClaudeBot:
    """Bridge Feishu messages to the selected AI backend runner."""

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: Path | None = None,
    ):
        """Initialize bot runtime components.

        Args:
            settings: Optional app settings object.
            workspace: Optional workspace override for Claude backend.
        """
        self.settings = settings or get_settings()
        self.workspace = workspace or self.settings.claude_workspace

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

        self._chat_states: dict[str, ChatRuntimeState] = {}
        self.feishu.set_message_handler(self._handle_message)

    async def start(self) -> None:
        """Start the bot and validate runtime prerequisites."""
        errors = self.settings.validate_feishu()
        if errors:
            raise ValueError("Configuration errors: " + "; ".join(errors))

        runner_name, runner = self._backend_runner(self.backend)
        available, info = runner.check_cli_available()
        if not available:
            raise RuntimeError(f"{runner_name} CLI not available: {info}")
        logger.info(f"{runner_name} CLI found at: {info}")

        await self.feishu.start()
        logger.info("FeishuClaude bot started")

    async def stop(self) -> None:
        """Stop bot resources."""
        await self.feishu.stop()
        logger.info("FeishuClaude bot stopped")

    async def _handle_message(self, msg: FeishuMessage) -> None:
        """Process incoming Feishu message end-to-end."""
        logger.info(f"Message from {msg.sender_id} in {msg.chat_id}: {msg.content[:50]}...")

        command_response = await self._process_command(msg)
        if command_response is not None:
            await self.feishu.send_message(msg.chat_id, command_response)
            return

        state = self._chat_state(msg.chat_id)
        try:
            if state.backend == "codex":
                await self._handle_codex_message(msg, state)
                return

            await self._handle_claude_message(msg, state)

        except Exception as exc:
            logger.error(f"Error processing message: {exc}")
            await self.feishu.send_message(msg.chat_id, f"❌ Internal error: {exc}")

    async def _handle_codex_message(self, msg: FeishuMessage, state: ChatRuntimeState) -> None:
        """Handle one message with Codex runner and staged Feishu responses.

        Args:
            msg: Incoming Feishu message.
            state: Chat-scoped runtime state.
        """
        await self.feishu.send_message(msg.chat_id, self._ack_text(state))

        start_monotonic = time.monotonic()
        last_progress_monotonic = start_monotonic
        last_progress_event_count = 0

        async def progress_callback(
            event_count: int,
            event: dict[str, Any],
            summary: CodexEventSummary,
        ) -> None:
            """Emit threshold-based progress updates to Feishu."""
            nonlocal last_progress_event_count, last_progress_monotonic
            del event, summary

            if not self.settings.feishu_progress_updates_enabled:
                return

            elapsed = time.monotonic() - start_monotonic
            if elapsed < self.settings.feishu_progress_min_seconds:
                return

            if event_count - last_progress_event_count < self.settings.feishu_progress_event_interval:
                return

            if (
                time.monotonic() - last_progress_monotonic
                < self.settings.feishu_progress_min_interval_seconds
            ):
                return

            last_progress_event_count = event_count
            last_progress_monotonic = time.monotonic()
            await self.feishu.send_message(
                msg.chat_id,
                self._progress_text(state, event_count, elapsed),
            )

        response = await self.codex.send_message(
            chat_id=msg.chat_id,
            message=msg.content,
            continue_session=True,
            mode=state.mode,
            model=state.effective_model(self.settings.codex_model),
            search_enabled=state.search_enabled,
            progress_callback=progress_callback,
        )

        prompt_hash = hashlib.sha256(msg.content.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "codex_run chat_id=%s mode=%s prompt_hash=%s events=%d duration_ms=%s cost_usd=%s "
            "is_error=%s",
            msg.chat_id,
            state.mode,
            prompt_hash,
            response.event_count,
            response.duration_ms,
            response.cost_usd,
            response.is_error,
        )

        footer = self._footer_text(state, response)
        if response.is_error:
            await self.feishu.send_message(
                msg.chat_id,
                self._format_error(state, response.content, footer),
            )
            return

        await self.feishu.send_message(
            msg.chat_id,
            self._format_final(state, response.content, footer),
        )

    async def _handle_claude_message(self, msg: FeishuMessage, state: ChatRuntimeState) -> None:
        """Handle one message with Claude backend.

        Args:
            msg: Incoming Feishu message.
            state: Chat-scoped runtime state.
        """
        session = self.claude.get_or_create_session(msg.chat_id)
        session.model = state.effective_model(self.settings.claude_model)
        response = await self.claude.send_message(
            chat_id=msg.chat_id,
            message=msg.content,
            continue_session=True,
        )

        if response.is_error:
            logger.error(f"Runner error: {response.content}")
            await self.feishu.send_message(msg.chat_id, f"❌ {response.content}")
            return

        await self.feishu.send_message(msg.chat_id, response.content)

    async def _process_command(self, msg: FeishuMessage) -> str | None:
        """Process bot commands and return response text when matched."""
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

        return None

    def _help_text(self) -> str:
        """Return command help text."""
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
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def _backend_runner(self, backend: BackendType) -> tuple[str, ClaudeRunner | CodexRunner]:
        """Get backend runner by backend id."""
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
                language=self.settings.feishu_default_language,
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
        mode: str = value
        state.mode = mode  # type: ignore[assignment]
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

    def _ack_text(self, state: ChatRuntimeState) -> str:
        """Return immediate acknowledgement text."""
        if state.language == "en":
            return "Received. Processing..."
        return "已收到，处理中..."

    def _progress_text(self, state: ChatRuntimeState, event_count: int, elapsed: float) -> str:
        """Build progress message for long-running tasks."""
        if state.language == "en":
            return f"Still working... events={event_count}, elapsed={elapsed:.1f}s"
        return f"处理中... 事件: {event_count}，耗时: {elapsed:.1f}s"

    def _footer_text(self, state: ChatRuntimeState, response: ClaudeResponse) -> str:
        """Build compact execution footer."""
        seconds = (response.duration_ms or 0) / 1000.0
        cost = response.cost_usd if response.cost_usd is not None else 0.0
        if state.language == "en":
            return (
                f"Mode: {state.mode} | Duration: {seconds:.1f}s | "
                f"Events: {response.event_count} | EstCost: ${cost:.4f}"
            )
        return (
            f"模式: {state.mode} | 耗时: {seconds:.1f}s | "
            f"事件: {response.event_count} | 估算成本: ${cost:.4f}"
        )

    def _format_final(self, state: ChatRuntimeState, content: str, footer: str) -> str:
        """Format successful final response message."""
        final_content = content.strip()
        if not final_content:
            final_content = "已完成，但未返回文本结果。" if state.language == "zh" else "Done with no text output."
        return f"{final_content}\n\n{footer}"

    def _format_error(self, state: ChatRuntimeState, content: str, footer: str) -> str:
        """Format failed final response message."""
        if state.language == "en":
            return f"❌ Failed: {content}\n\n{footer}"
        return f"❌ 执行失败: {content}\n\n{footer}"
