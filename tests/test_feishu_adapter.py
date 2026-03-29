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


class _FakeResponse:
    """Minimal HTTP response test double."""

    def __init__(self, *, code: int = 0, msg: str = "ok"):
        self._data = {"code": code, "msg": msg}

    def raise_for_status(self) -> None:
        """No-op status checker for successful fake responses."""

    def json(self) -> dict[str, object]:
        """Return fake JSON payload."""
        return self._data


class _FakeAsyncClient:
    """Minimal async HTTP client test double."""

    def __init__(self, responses: dict[str, _FakeResponse]):
        self.responses = responses
        self.urls: list[str] = []

    async def post(self, url: str, json: dict, headers: dict[str, str]) -> _FakeResponse:
        """Record request URL and return predefined response."""
        del json, headers
        self.urls.append(url)
        for pattern, response in self.responses.items():
            if pattern in url:
                return response
        raise AssertionError(f"Unexpected URL in test: {url}")


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


@pytest.mark.asyncio
async def test_send_message_falls_back_to_reply(monkeypatch):
    """Adapter should retry via reply API when chat send fails."""
    config = FeishuConfig(app_id="app", app_secret="secret")
    adapter = FeishuAdapter(config)

    fake_client = _FakeAsyncClient(
        responses={
            "receive_id_type=chat_id": _FakeResponse(code=99991663, msg="forbidden"),
            "/reply": _FakeResponse(code=0, msg="ok"),
        }
    )
    adapter._client = fake_client
    adapter._remember_latest_message_id("chat_1", "om_1")

    async def fake_token() -> str:
        return "tenant_token"

    monkeypatch.setattr(adapter, "_get_tenant_access_token", fake_token)

    result = await adapter.send_message("chat_1", "hello")

    assert result is True
    assert any("receive_id_type=chat_id" in url for url in fake_client.urls)
    assert any("/im/v1/messages/om_1/reply" in url for url in fake_client.urls)


@pytest.mark.asyncio
async def test_send_message_fails_without_reply_fallback(monkeypatch):
    """Adapter should return False when primary send fails and no reply target exists."""
    config = FeishuConfig(app_id="app", app_secret="secret")
    adapter = FeishuAdapter(config)
    adapter._client = _FakeAsyncClient(
        responses={
            "receive_id_type=chat_id": _FakeResponse(code=99991663, msg="forbidden"),
        }
    )

    async def fake_token() -> str:
        return "tenant_token"

    monkeypatch.setattr(adapter, "_get_tenant_access_token", fake_token)

    result = await adapter.send_message("chat_missing", "hello")

    assert result is False
