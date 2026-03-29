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
from .policy import ExecPolicyChecker
from .runtime_state import BackendType, ChatRuntimeState
from .safety import RiskIntentDetector

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
        self.risk_detector = RiskIntentDetector()
        self.policy_checker = ExecPolicyChecker(self.settings.codex_execpolicy_rule_paths)
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
        state = self._chat_state(msg.chat_id)

        normalized = msg.content.strip().lower()
        if normalized == "/confirm":
            await self._handle_confirm_command(msg, state)
            return
        if normalized == "/cancel":
            await self._handle_cancel_command(msg, state)
            return

        command_response = await self._process_command(msg)
        if command_response is not None:
            await self.feishu.send_message(msg.chat_id, command_response)
            return

        try:
            if state.backend == "codex":
                await self._execute_codex_prompt_with_safety(
                    msg=msg,
                    state=state,
                    prompt=msg.content,
                    confirmation_granted=False,
                )
                return

            guardrail_block = self._guardrail_block_text(state)
            if guardrail_block:
                await self.feishu.send_message(msg.chat_id, guardrail_block)
                return

            await self._handle_claude_message(msg, state)

        except Exception as exc:
            logger.error(f"Error processing message: {exc}")
            await self.feishu.send_message(msg.chat_id, f"❌ Internal error: {exc}")

    async def _handle_codex_message(
        self,
        msg: FeishuMessage,
        state: ChatRuntimeState,
        prompt: str,
    ) -> None:
        """Handle one message with Codex runner and staged Feishu responses.

        Args:
            msg: Incoming Feishu message.
            state: Chat-scoped runtime state.
            prompt: Prompt text to execute after preflight checks.
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
            message=prompt,
            continue_session=True,
            mode=state.mode,
            model=state.effective_model(self.settings.codex_model),
            search_enabled=state.search_enabled,
            progress_callback=progress_callback,
        )
        self._record_usage(state, response)

        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
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
        self._record_usage(state, response)

        if response.is_error:
            logger.error(f"Runner error: {response.content}")
            await self.feishu.send_message(msg.chat_id, f"❌ {response.content}")
            return

        await self.feishu.send_message(msg.chat_id, response.content)

    async def _execute_codex_prompt_with_safety(
        self,
        *,
        msg: FeishuMessage,
        state: ChatRuntimeState,
        prompt: str,
        confirmation_granted: bool,
    ) -> None:
        """Apply safety and policy gates before executing a Codex prompt.

        Args:
            msg: Original Feishu message envelope.
            state: Chat runtime state.
            prompt: Prompt text to execute.
            confirmation_granted: Whether explicit user confirmation has been provided.
        """
        stripped_prompt = prompt.strip()
        if not stripped_prompt:
            await self.feishu.send_message(msg.chat_id, "Empty prompt ignored.")
            return

        guardrail_block = self._guardrail_block_text(state)
        if guardrail_block:
            await self.feishu.send_message(msg.chat_id, guardrail_block)
            return

        if state.pending_confirmation_prompt and not confirmation_granted:
            await self.feishu.send_message(msg.chat_id, self._pending_confirmation_text(state))
            return

        risk = self.risk_detector.assess(stripped_prompt)
        if risk.is_risky and not confirmation_granted:
            state.pending_confirmation_prompt = stripped_prompt
            state.pending_confirmation_reason = risk.reason
            logger.info(
                "safety_gate chat_id=%s decision=prompt reason=%s",
                msg.chat_id,
                risk.reason,
            )
            await self.feishu.send_message(msg.chat_id, self._confirmation_prompt_text(state, risk.reason))
            return

        policy_decision = await self.policy_checker.check(stripped_prompt)
        logger.info(
            "policy_preflight chat_id=%s mode=%s decision=%s reason=%s",
            msg.chat_id,
            state.mode,
            policy_decision.decision,
            policy_decision.reason,
        )
        if policy_decision.decision in {"block", "unknown"}:
            await self.feishu.send_message(
                msg.chat_id,
                self._policy_block_text(state, policy_decision.reason),
            )
            return
        if policy_decision.decision == "prompt" and not confirmation_granted:
            state.pending_confirmation_prompt = stripped_prompt
            state.pending_confirmation_reason = f"policy: {policy_decision.reason}"
            await self.feishu.send_message(
                msg.chat_id,
                self._confirmation_prompt_text(state, state.pending_confirmation_reason),
            )
            return

        await self._handle_codex_message(msg, state, stripped_prompt)

    async def _handle_confirm_command(self, msg: FeishuMessage, state: ChatRuntimeState) -> None:
        """Execute pending risky prompt after explicit user confirmation."""
        pending_prompt = state.pending_confirmation_prompt
        if not pending_prompt:
            await self.feishu.send_message(msg.chat_id, self._no_pending_confirmation_text(state))
            return

        state.pending_confirmation_prompt = None
        state.pending_confirmation_reason = None
        await self._execute_codex_prompt_with_safety(
            msg=msg,
            state=state,
            prompt=pending_prompt,
            confirmation_granted=True,
        )

    async def _handle_cancel_command(self, msg: FeishuMessage, state: ChatRuntimeState) -> None:
        """Cancel pending risky prompt if present."""
        if not state.pending_confirmation_prompt:
            await self.feishu.send_message(msg.chat_id, self._no_pending_confirmation_text(state))
            return
        state.pending_confirmation_prompt = None
        state.pending_confirmation_reason = None
        if state.language == "en":
            await self.feishu.send_message(msg.chat_id, "Pending risky action canceled.")
        else:
            await self.feishu.send_message(msg.chat_id, "已取消待确认的风险操作。")

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

        if cmd == "/turns":
            return self._handle_turns_command(tokens, state)

        if cmd == "/budget":
            return self._handle_budget_command(tokens, state)

        if cmd == "/tools":
            return self._tools_text(state)

        if cmd == "/status":
            runner_name, runner = self._backend_runner(state.backend)
            available, info = runner.check_cli_available()
            status = "✅" if available else "❌"
            return (
                f"🤖 FeishuClaude Status\n"
                f"Backend: {state.backend}\n"
                f"Backend note: {self._backend_note(state.backend)}\n"
                f"Mode: {state.mode}\n"
                f"Search: {'on' if state.search_enabled else 'off'}\n"
                f"Pending confirmation: {'yes' if state.pending_confirmation_prompt else 'no'}\n"
                f"Turns: {self._turns_status_text(state)}\n"
                f"Budget: {self._budget_status_text(state)}\n"
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
            "/turns <n|off> - Set per-chat turn limit\n"
            "/budget <usd|off> - Set per-chat budget limit\n"
            "/tools - Show effective safety controls\n"
            "/confirm - Execute pending risky action\n"
            "/cancel - Cancel pending risky action\n"
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
                turn_limit=self.settings.feishu_default_turn_limit,
                budget_limit_usd=self.settings.feishu_default_budget_usd,
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

    def _backend_note(self, backend: BackendType) -> str:
        """Return backend rollout note for status output."""
        if backend == "codex":
            return "default"
        return "rollback-only (deprecated)"

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

    def _handle_turns_command(self, tokens: list[str], state: ChatRuntimeState) -> str:
        """Handle `/turns` command parsing and state update."""
        if len(tokens) != 2:
            return "Usage: /turns <n|off>"
        value = tokens[1].strip().lower()
        if value in {"off", "none", "unlimited"}:
            state.turn_limit = None
            return "Turn limit disabled for this chat."

        try:
            limit = int(value)
        except ValueError:
            return "Invalid turns value. Use a positive integer or /turns off."

        if limit <= 0:
            return "Turn limit must be greater than 0."

        state.turn_limit = limit
        return f"Turn limit set to {limit}."

    def _handle_budget_command(self, tokens: list[str], state: ChatRuntimeState) -> str:
        """Handle `/budget` command parsing and state update."""
        if len(tokens) != 2:
            return "Usage: /budget <usd|off>"
        value = tokens[1].strip().lower()
        if value in {"off", "none", "unlimited"}:
            state.budget_limit_usd = None
            return "Budget limit disabled for this chat."

        try:
            limit = float(value)
        except ValueError:
            return "Invalid budget value. Use a positive number or /budget off."

        if limit <= 0:
            return "Budget limit must be greater than 0."

        state.budget_limit_usd = limit
        return f"Budget limit set to ${limit:.4f}."

    def _tools_text(self, state: ChatRuntimeState) -> str:
        """Return chat-scoped safety control snapshot."""
        if state.backend != "codex":
            return (
                "Tools snapshot\n"
                "Backend: claude\n"
                "Claude backend is rollback-only and deprecated.\n"
                "Codex safety controls are available after switching backend to codex."
            )

        flags = " ".join(MODE_FLAG_MAP[state.mode])
        return (
            "Tools snapshot\n"
            f"Backend: codex\n"
            f"Mode: {state.mode}\n"
            f"Flags: {flags}\n"
            f"Search: {'on' if state.search_enabled else 'off'}\n"
            f"Model: {state.model or self.settings.codex_model or 'default'}\n"
            f"ExecPolicy rules: {self._policy_rules_text()}\n"
            f"Turns: {self._turns_status_text(state)}\n"
            f"Budget: {self._budget_status_text(state)}"
        )

    def _policy_rules_text(self) -> str:
        """Return compact text for configured execpolicy rules."""
        if not self.policy_checker.enabled:
            return "disabled"
        return ",".join(str(rule) for rule in self.policy_checker.rules)

    def _confirmation_prompt_text(self, state: ChatRuntimeState, reason: str) -> str:
        """Build confirmation request message for risky operations."""
        if state.language == "en":
            return (
                f"Risk gate triggered ({reason}). Reply /confirm to run, or /cancel to stop."
            )
        return f"检测到高风险操作（{reason}）。回复 /confirm 执行，或 /cancel 取消。"

    def _pending_confirmation_text(self, state: ChatRuntimeState) -> str:
        """Return message when a risk decision is pending user action."""
        if state.language == "en":
            return "A risky action is pending. Reply /confirm or /cancel first."
        return "有待确认的风险操作。请先回复 /confirm 或 /cancel。"

    def _no_pending_confirmation_text(self, state: ChatRuntimeState) -> str:
        """Return message when no pending confirmation exists."""
        if state.language == "en":
            return "No pending risky action."
        return "当前没有待确认的风险操作。"

    def _policy_block_text(self, state: ChatRuntimeState, reason: str) -> str:
        """Return policy-block response message."""
        if state.language == "en":
            return f"Blocked by policy: {reason}"
        return f"已被策略阻止：{reason}"

    def _guardrail_block_text(self, state: ChatRuntimeState) -> str | None:
        """Return guardrail limit-hit message when execution should be blocked."""
        if state.turn_limit is not None and state.turns_used >= state.turn_limit:
            if state.language == "en":
                return f"Turn limit reached ({state.turns_used}/{state.turn_limit})."
            return f"已达到轮次上限（{state.turns_used}/{state.turn_limit}）。"

        if state.budget_limit_usd is not None and state.budget_used_usd >= state.budget_limit_usd:
            if state.language == "en":
                return (
                    "Budget limit reached "
                    f"(${state.budget_used_usd:.4f}/${state.budget_limit_usd:.4f})."
                )
            return (
                "已达到预算上限 "
                f"(${state.budget_used_usd:.4f}/${state.budget_limit_usd:.4f})。"
            )
        return None

    def _record_usage(self, state: ChatRuntimeState, response: ClaudeResponse) -> None:
        """Record turn and budget usage after one backend attempt."""
        state.turns_used += 1
        if response.cost_usd is not None and response.cost_usd > 0:
            state.budget_used_usd += response.cost_usd

    def _turns_status_text(self, state: ChatRuntimeState) -> str:
        """Return turns usage text for status output."""
        if state.turn_limit is None:
            return f"{state.turns_used}/unlimited"
        remaining = max(state.turn_limit - state.turns_used, 0)
        return f"{state.turns_used}/{state.turn_limit} (remaining {remaining})"

    def _budget_status_text(self, state: ChatRuntimeState) -> str:
        """Return budget usage text for status output."""
        if state.budget_limit_usd is None:
            return f"${state.budget_used_usd:.4f}/unlimited"
        remaining = max(state.budget_limit_usd - state.budget_used_usd, 0.0)
        return (
            f"${state.budget_used_usd:.4f}/${state.budget_limit_usd:.4f} "
            f"(remaining ${remaining:.4f})"
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
