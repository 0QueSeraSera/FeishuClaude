"""Tests for bot logic."""

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage


@pytest.fixture
def test_settings():
    """Create test settings."""
    return Settings(
        feishu_app_id="test_app_id",
        feishu_app_secret="test_app_secret",
        feishu_connection_mode="long_connection",
    )


def test_bot_init(test_settings):
    """Test bot initialization."""
    bot = FeishuClaudeBot(settings=test_settings)
    assert bot.settings is test_settings
    assert bot.feishu is not None
    assert bot.claude is not None


def test_help_command(test_settings):
    """Test help command processing."""
    bot = FeishuClaudeBot(settings=test_settings)
    help_text = bot._help_text()

    assert "/help" in help_text
    assert "/new" in help_text
    assert "/status" in help_text


@pytest.mark.asyncio
async def test_command_processing(test_settings):
    """Test command processing."""
    bot = FeishuClaudeBot(settings=test_settings)

    # Help command
    msg = FeishuMessage(
        chat_id="chat_123",
        sender_id="user_456",
        content="/help",
    )
    response = await bot._process_command(msg)
    assert response is not None
    assert "/help" in response

    # New session command
    msg = FeishuMessage(
        chat_id="chat_123",
        sender_id="user_456",
        content="/new",
    )
    response = await bot._process_command(msg)
    assert response is not None
    assert "new" in response.lower()

    # Ping command
    msg = FeishuMessage(
        chat_id="chat_123",
        sender_id="user_456",
        content="/ping",
    )
    response = await bot._process_command(msg)
    assert response == "pong 🏓"

    # Non-command
    msg = FeishuMessage(
        chat_id="chat_123",
        sender_id="user_456",
        content="Hello there!",
    )
    response = await bot._process_command(msg)
    assert response is None
