"""Tests for Claude runner."""

import pytest

from feishu_claude.claude_runner import ClaudeRunner, ClaudeSession


def test_session_build_args():
    """Test CLI argument building."""
    session = ClaudeSession()

    # Basic prompt
    args = session.build_args("Hello", continue_session=False)
    assert "claude" in args[0]
    assert "--print" in args
    assert "Hello" in args
    assert "--dangerously-skip-permissions" in args

    # With model
    session.model = "claude-sonnet-4-6"
    args = session.build_args("Hello", continue_session=False)
    assert "--model" in args
    assert "claude-sonnet-4-6" in args

    # With max turns
    session.max_turns = 5
    args = session.build_args("Hello", continue_session=False)
    assert "--max-turns" in args
    assert "5" in args


def test_runner_session_management():
    """Test session management."""
    runner = ClaudeRunner()
    assert len(runner.list_sessions()) == 0

    # Create session
    session = runner.get_or_create_session("chat_123")
    assert session is not None
    assert len(runner.list_sessions()) == 1

    # Get existing session
    session2 = runner.get_or_create_session("chat_123")
    assert session2 is session

    # Reset session
    assert runner.reset_session("chat_123") is True
    assert len(runner.list_sessions()) == 0
    assert runner.reset_session("nonexistent") is False


@pytest.mark.asyncio
async def test_runner_send_without_cli():
    """Test that send handles missing CLI gracefully."""
    # This test will fail if Claude CLI is not installed
    # which is expected in CI environments
    runner = ClaudeRunner()
    response = await runner.send_message("test_chat", "Hello")

    # Should either succeed or return an error response
    assert response is not None
    if response.is_error:
        assert "not found" in response.content.lower() or "error" in response.content.lower()
