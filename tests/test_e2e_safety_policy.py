"""In-process E2E tests for safety confirmation and policy block behavior."""

from __future__ import annotations

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.claude_runner import ClaudeResponse
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage
from feishu_claude.policy import PolicyDecision


@pytest.mark.asyncio
async def test_e2e_risky_prompt_requires_confirmation():
    """Risky prompt should not execute until user explicitly confirms."""
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
        return ClaudeResponse(content="executed", event_count=2, duration_ms=500)

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_safe", sender_id="user_a", content="delete all files")
    )
    assert calls["codex"] == 0
    assert "/confirm" in sent[-1][1]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_safe", sender_id="user_a", content="/confirm")
    )
    assert calls["codex"] == 1
    assert sent[-1][0] == "chat_safe"
    assert "executed" in sent[-1][1]


@pytest.mark.asyncio
async def test_e2e_policy_block_returns_reason():
    """Policy block should prevent execution and return explicit reason."""
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
        return ClaudeResponse(content="should not run")

    async def fake_policy_check(prompt: str):
        del prompt
        return PolicyDecision(decision="block", reason="blocked by test policy")

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]
    bot.policy_checker.check = fake_policy_check  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_policy", sender_id="user_b", content="run harmless command")
    )

    assert calls["codex"] == 0
    assert "策略阻止" in sent[-1][1] or "policy" in sent[-1][1].lower()
