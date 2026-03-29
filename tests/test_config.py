"""Tests for configuration."""

import pytest

from feishu_claude.config import Settings


@pytest.fixture(autouse=True)
def clear_relevant_env(monkeypatch):
    """Clear env vars that can leak local settings into tests."""
    for key in (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_CONNECTION_MODE",
        "FEISHU_ALLOW_GROUP_CHATS",
        "FEISHU_ALLOW_USER_IDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults():
    """Test default settings values."""
    settings = Settings(_env_file=None)
    assert settings.feishu_connection_mode == "long_connection"
    assert settings.feishu_allow_group_chats is True
    assert settings.feishu_backend == "codex"


def test_settings_validation():
    """Test configuration validation."""
    settings = Settings(
        _env_file=None,
        feishu_app_id="",  # Empty should fail
        feishu_app_secret="",  # Empty should fail
    )
    errors = settings.validate_feishu()
    assert len(errors) == 2
    assert any("APP_ID" in e for e in errors)
    assert any("APP_SECRET" in e for e in errors)


def test_allowed_user_ids_parsing():
    """Test parsing of allowed user IDs."""
    # Need to pass via environment or use the correct field name
    import os

    os.environ["FEISHU_ALLOW_USER_IDS"] = "ou_123, ou_456 , ou_789"
    settings = Settings(_env_file=None)
    assert settings.allowed_user_ids == {"ou_123", "ou_456", "ou_789"}
    del os.environ["FEISHU_ALLOW_USER_IDS"]

    settings = Settings(_env_file=None)
    assert settings.allowed_user_ids == set()
