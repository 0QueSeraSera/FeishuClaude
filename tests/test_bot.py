"""Tests for bot logic."""

import pytest

from feishu_claude.bot import FeishuClaudeBot
from feishu_claude.config import Settings
from feishu_claude.feishu_adapter import FeishuMessage


@pytest.fixture(autouse=True)
def clear_bot_env(monkeypatch):
    """Clear env vars that could affect backend selection tests."""
    for key in (
        "FEISHU_BACKEND",
        "CLAUDE_MODEL",
        "CODEX_MODEL",
        "CODEX_DEFAULT_MODE",
        "CODEX_SEARCH_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def test_settings():
    """Create test settings."""
    return Settings(
        _env_file=None,
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
    assert bot.codex is not None
    assert bot.backend == "claude"


def test_bot_backend_selection_codex(test_settings):
    """Test backend selector can route to Codex."""
    codex_settings = test_settings.model_copy(update={"feishu_backend": "codex"})
    bot = FeishuClaudeBot(settings=codex_settings)
    backend_name, runner = bot._selected_backend_runner()
    assert backend_name == "Codex"
    assert runner is bot.codex


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


@pytest.mark.asyncio
async def test_status_command_includes_backend(test_settings):
    """Status output should include active backend details."""
    codex_settings = test_settings.model_copy(update={"feishu_backend": "codex"})
    bot = FeishuClaudeBot(settings=codex_settings)
    response = await bot._process_command(
        FeishuMessage(chat_id="chat_123", sender_id="user_456", content="/status")
    )
    assert response is not None
    assert "Backend: codex" in response


@pytest.mark.asyncio
async def test_start_fails_when_selected_backend_cli_missing(test_settings, monkeypatch):
    """Startup checks should fail if selected backend CLI is unavailable."""
    codex_settings = test_settings.model_copy(update={"feishu_backend": "codex"})
    bot = FeishuClaudeBot(settings=codex_settings)

    monkeypatch.setattr(bot.codex, "check_cli_available", lambda: (False, "missing"))

    with pytest.raises(RuntimeError) as exc:
        await bot.start()
    assert "Codex CLI not available" in str(exc.value)
