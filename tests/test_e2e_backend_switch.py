"""In-process E2E tests for backend selection and rollback."""

from __future__ import annotations

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.claude_runner import ClaudeResponse
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage


@pytest.mark.asyncio
async def test_e2e_message_uses_codex_backend():
    """When backend is codex, message should be routed to Codex runner."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="codex",
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []
    calls = {"codex": 0, "claude": 0}

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
    ):
        calls["codex"] += 1
        return ClaudeResponse(content=f"codex:{message}")

    async def fake_claude(chat_id: str, message: str, continue_session: bool = True):
        calls["claude"] += 1
        return ClaudeResponse(content=f"claude:{message}")

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]
    bot.claude.send_message = fake_claude  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_1", sender_id="user_1", content="ping codex")
    )

    assert sent == [("chat_1", "codex:ping codex")]
    assert calls == {"codex": 1, "claude": 0}


@pytest.mark.asyncio
async def test_e2e_backend_rollback_to_claude():
    """Switching backend to claude should route without code changes."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="claude",
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []
    calls = {"codex": 0, "claude": 0}

    async def fake_send(chat_id: str, content: str) -> bool:
        sent.append((chat_id, content))
        return True

    async def fake_codex(chat_id: str, message: str, continue_session: bool = True):
        calls["codex"] += 1
        return ClaudeResponse(content=f"codex:{message}")

    async def fake_claude(chat_id: str, message: str, continue_session: bool = True):
        calls["claude"] += 1
        return ClaudeResponse(content=f"claude:{message}")

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]
    bot.claude.send_message = fake_claude  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(chat_id="chat_2", sender_id="user_2", content="ping claude")
    )

    assert sent == [("chat_2", "claude:ping claude")]
    assert calls == {"codex": 0, "claude": 1}


@pytest.mark.asyncio
async def test_e2e_mode_switch_applies_to_codex_runtime():
    """Mode/model/search settings should affect downstream codex invocation."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_backend="codex",
    )
    bot = FeishuClaudeBot(settings=settings)
    sent: list[tuple[str, str]] = []
    captured: dict[str, object] = {}

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
    ):
        captured.update(
            {
                "chat_id": chat_id,
                "message": message,
                "mode": mode,
                "model": model,
                "search_enabled": search_enabled,
            }
        )
        return ClaudeResponse(content="done")

    bot.feishu.send_message = fake_send  # type: ignore[method-assign]
    bot.codex.send_message = fake_codex  # type: ignore[method-assign]

    await bot._process_command(
        FeishuMessage(chat_id="chat_3", sender_id="user_3", content="/mode normal")
    )
    await bot._process_command(
        FeishuMessage(chat_id="chat_3", sender_id="user_3", content="/model gpt-5-codex")
    )
    await bot._process_command(
        FeishuMessage(chat_id="chat_3", sender_id="user_3", content="/search on")
    )

    await bot._handle_message(
        FeishuMessage(chat_id="chat_3", sender_id="user_3", content="请分析这个仓库")
    )

    assert captured["mode"] == "normal"
    assert captured["model"] == "gpt-5-codex"
    assert captured["search_enabled"] is True
    assert sent[-1] == ("chat_3", "done")
