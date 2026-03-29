"""Tests for Feishu adapter."""

import pytest

from feishu_claude.feishu_adapter import (
    FeishuAdapter,
    FeishuConfig,
    FeishuMessage,
    _extract_message_text,
    _extract_post_text,
    _str_or_none,
)


def test_str_or_none():
    """Test string conversion helper."""
    assert _str_or_none("hello") == "hello"
    assert _str_or_none("  hello  ") == "hello"
    assert _str_or_none("") is None
    assert _str_or_none("   ") is None
    assert _str_or_none(123) is None
    assert _str_or_none(None) is None


def test_extract_message_text():
    """Test message text extraction."""
    # Simple text message
    assert _extract_message_text("text", '{"text": "Hello"}') == "Hello"

    # Text with whitespace
    assert _extract_message_text("text", '{"text": "  Hello  "}') == "Hello"

    # Already parsed content
    assert _extract_message_text("text", {"text": "Hello"}) == "Hello"

    # Image placeholder
    assert _extract_message_text("image", {}) == "[image]"

    # Audio placeholder
    assert _extract_message_text("audio", {}) == "[audio]"


def test_extract_post_text():
    """Test rich post text extraction."""
    content = {
        "content": [
            [{"tag": "text", "text": "Hello "}],
            [{"tag": "at", "user_name": "John"}, {"tag": "text", "text": "!"}],
        ]
    }
    result = _extract_post_text(content)
    assert "Hello" in result
    assert "@John" in result


def test_feishu_config():
    """Test config creation."""
    config = FeishuConfig(
        app_id="test_id",
        app_secret="test_secret",
        allow_user_ids={"user1", "user2"},
        allow_group_chats=False,
    )

    assert config.app_id == "test_id"
    assert config.app_secret == "test_secret"
    assert "user1" in config.allow_user_ids
    assert config.allow_group_chats is False


def test_feishu_adapter_validation():
    """Test adapter config validation."""
    # Missing required fields
    config = FeishuConfig(app_id="", app_secret="")
    adapter = FeishuAdapter(config)
    errors = adapter.validate_config()
    assert len(errors) == 2
    assert any("APP_ID" in e for e in errors)
    assert any("APP_SECRET" in e for e in errors)

    # Valid config
    config = FeishuConfig(app_id="test", app_secret="test")
    adapter = FeishuAdapter(config)
    errors = adapter.validate_config()
    assert len(errors) == 0


def test_feishu_adapter_validation_rejects_webhook_mode():
    """Webhook mode should fail validation until transport is implemented."""
    config = FeishuConfig(
        app_id="test",
        app_secret="test",
        connection_mode="webhook",
    )
    adapter = FeishuAdapter(config)
    errors = adapter.validate_config()
    assert any("webhook is not implemented yet" in error for error in errors)


def test_feishu_message():
    """Test message dataclass."""
    msg = FeishuMessage(
        chat_id="chat_123",
        sender_id="user_456",
        content="Hello world",
        message_type="text",
        chat_type="p2p",
    )

    assert msg.chat_id == "chat_123"
    assert msg.sender_id == "user_456"
    assert msg.content == "Hello world"
    assert msg.message_type == "text"
    assert msg.chat_type == "p2p"
