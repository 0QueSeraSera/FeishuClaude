"""In-process E2E tests for Codex response staging and formatting."""

from __future__ import annotations

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.claude_runner import ClaudeResponse
from feishu_claude.codex_runner import CodexEventSummary
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage


@pytest.mark.asyncio
async def test_e2e_codex_ack_and_final_footer():
    """Codex backend should send ack first, then final with compact footer."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="codex",
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []

    async def fake_send(chat_id: str, content: str) -> bool:
        sent.append((chat_id, content))
        return True

    async def fake_codex(
        chat_id: str,
        message: str,
        continue_session: bool = True,
        *,
        mode=None,
        model=None,
        search_enabled=None,
        progress_callback=None,
    ):
        del chat_id, message, continue_session, mode, model, search_enabled, progress_callback
        return ClaudeResponse(
            content="已完成任务",
            event_count=5,
            duration_ms=1200,
            cost_usd=0.0123,
        )

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_ob", sender_id="user_ob", content="请处理这个任务")
    )

    assert sent[0] == ("chat_ob", "已收到，处理中...")
    assert "已完成任务" in sent[1][1]
    assert "模式: safe" in sent[1][1]
    assert "事件: 5" in sent[1][1]


@pytest.mark.asyncio
async def test_e2e_codex_progress_updates_for_long_run():
    """Progress updates should be emitted when threshold conditions are met."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="codex",
        feishu_progress_min_seconds=0.0,
        feishu_progress_event_interval=1,
        feishu_progress_min_interval_seconds=0.0,
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []

    async def fake_send(chat_id: str, content: str) -> bool:
        sent.append((chat_id, content))
        return True

    async def fake_codex(
        chat_id: str,
        message: str,
        continue_session: bool = True,
        *,
        mode=None,
        model=None,
        search_enabled=None,
        progress_callback=None,
    ):
        del chat_id, message, continue_session, mode, model, search_enabled
        assert progress_callback is not None
        summary = CodexEventSummary()
        for i in range(1, 4):
            await progress_callback(i, {"type": "tick"}, summary)
        return ClaudeResponse(content="done", event_count=3, duration_ms=800)

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_progress", sender_id="user_p", content="run long task")
    )

    assert sent[0] == ("chat_progress", "已收到，处理中...")
    assert any("处理中... 事件:" in item[1] for item in sent[1:-1])
    assert "done" in sent[-1][1]
