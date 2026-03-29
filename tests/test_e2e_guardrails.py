"""In-process E2E tests for budget/turn guardrails."""

from __future__ import annotations

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.claude_runner import ClaudeResponse
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage


@pytest.mark.asyncio
async def test_e2e_turn_limit_blocks_second_run():
    """Second run should be blocked when turn limit is reached."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="codex",
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []
    calls = {"codex": 0}

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
        calls["codex"] += 1
        return ClaudeResponse(content="ok", event_count=1, duration_ms=300)

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]

    await bot._process_command(
        FeishuMessage(chat_id="chat_turn", sender_id="u1", content="/turns 1")
    )

    await bot._handle_message(FeishuMessage(chat_id="chat_turn", sender_id="u1", content="first"))
    await bot._handle_message(FeishuMessage(chat_id="chat_turn", sender_id="u1", content="second"))

    assert calls["codex"] == 1
    assert "轮次上限" in sent[-1][1] or "turn limit" in sent[-1][1].lower()


@pytest.mark.asyncio
async def test_e2e_budget_limit_blocks_overage():
    """Run should be blocked after budget usage exceeds configured ceiling."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="codex",
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []
    calls = {"codex": 0}

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
        calls["codex"] += 1
        return ClaudeResponse(content="charged", event_count=1, duration_ms=300, cost_usd=0.02)

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]

    await bot._process_command(
        FeishuMessage(chat_id="chat_budget", sender_id="u2", content="/budget 0.01")
    )

    await bot._handle_message(FeishuMessage(chat_id="chat_budget", sender_id="u2", content="first"))
    await bot._handle_message(FeishuMessage(chat_id="chat_budget", sender_id="u2", content="second"))

    assert calls["codex"] == 1
    assert "预算上限" in sent[-1][1] or "budget limit" in sent[-1][1].lower()


@pytest.mark.asyncio
async def test_status_reflects_guardrail_limits():
    """Status should include configured guardrail limits and usage."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
    )
    bot = FeishuClaudeBot(settings=settings)

    await bot._process_command(
        FeishuMessage(chat_id="chat_status", sender_id="u3", content="/turns 5")
    )
    await bot._process_command(
        FeishuMessage(chat_id="chat_status", sender_id="u3", content="/budget 1")
    )
    status = await bot._process_command(
        FeishuMessage(chat_id="chat_status", sender_id="u3", content="/status")
    )
    assert status is not None
    assert "Turns:" in status
    assert "Budget:" in status
