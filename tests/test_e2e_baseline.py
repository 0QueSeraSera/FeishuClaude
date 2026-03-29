"""In-process E2E tests for baseline Feishu -> bot -> runner flow."""

from __future__ import annotations

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.claude_runner import ClaudeResponse
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage


@pytest.fixture
def test_settings() -> Settings:
    """Create deterministic settings for bot E2E tests."""
    return Settings(
        _env_file=None,
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_connection_mode="long_connection",
        feishu_backend="claude",
    )


@pytest.mark.asyncio
async def test_e2e_p2p_message_to_reply(test_settings: Settings):
    """Ensure a normal p2p message reaches the runner and replies to Feishu."""
    bot = FeishuClaudeBot(settings=test_settings)
    sent_messages: list[tuple[str, str]] = []

    async def fake_send_message(chat_id: str, content: str) -> bool:
        sent_messages.append((chat_id, content))
        return True

    async def fake_runner_send_message(chat_id: str, message: str, continue_session: bool = True):
        assert chat_id == "chat_p2p"
        assert message == "你好，介绍一下你自己"
        assert continue_session is True
        return ClaudeResponse(content="这是基线回复")

    bot.feishu.send_message = fake_send_message  # type: ignore[method-assign]
    bot.claude.send_message = fake_runner_send_message  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(
            chat_id="chat_p2p",
            sender_id="user_1",
            content="你好，介绍一下你自己",
            chat_type="p2p",
        )
    )

    assert sent_messages == [("chat_p2p", "这是基线回复")]


@pytest.mark.asyncio
async def test_e2e_group_message_to_reply(test_settings: Settings):
    """Ensure group-chat path can produce a reply in baseline behavior."""
    bot = FeishuClaudeBot(settings=test_settings)
    sent_messages: list[tuple[str, str]] = []

    async def fake_send_message(chat_id: str, content: str) -> bool:
        sent_messages.append((chat_id, content))
        return True

    async def fake_runner_send_message(chat_id: str, message: str, continue_session: bool = True):
        assert chat_id == "chat_group"
        assert message == "@bot 请总结今天会议"
        return ClaudeResponse(content="会议总结如下")

    bot.feishu.send_message = fake_send_message  # type: ignore[method-assign]
    bot.claude.send_message = fake_runner_send_message  # type: ignore[method-assign]

    await bot._handle_message(
        FeishuMessage(
            chat_id="chat_group",
            sender_id="user_2",
            content="@bot 请总结今天会议",
            chat_type="group",
        )
    )

    assert sent_messages == [("chat_group", "会议总结如下")]
