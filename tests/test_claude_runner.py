"""Tests for Claude runner."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from feishu_claude.claude_runner import ClaudeRunner, ClaudeSession


class _FakeProcess:
    """Minimal fake asyncio subprocess process for runner tests."""

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return configured stdout/stderr payload."""
        return self._stdout, self._stderr


def test_session_build_args():
    """Test CLI argument building."""
    session = ClaudeSession()

    # Basic prompt
    args = session.build_args("Hello", continue_session=False)
    assert "claude" in args[0]
    assert "--print" in args
    assert "Hello" in args

    # Continue with explicit session id
    session.session_id = "ses_123"
    args = session.build_args("Hello", continue_session=True)
    assert "--resume" in args
    assert "ses_123" in args

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


def test_check_cli_available(monkeypatch: pytest.MonkeyPatch):
    """Test CLI availability checks."""
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/claude")
    available, info = ClaudeRunner.check_cli_available()
    assert available is True
    assert "claude" in info

    monkeypatch.setattr(shutil, "which", lambda _: None)
    available, info = ClaudeRunner.check_cli_available()
    assert available is False
    assert "not found" in info.lower()


@pytest.mark.asyncio
async def test_session_send_success(monkeypatch: pytest.MonkeyPatch):
    """Test successful subprocess response path."""
    expected_workspace = Path("/tmp/workspace")

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert args[0] == "claude"
        assert kwargs["cwd"] == str(expected_workspace)
        return _FakeProcess(returncode=0, stdout=b"Hello from Claude\n", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    response = await ClaudeSession(workspace=expected_workspace).send("Hello")
    assert response.is_error is False
    assert response.content == "Hello from Claude"


@pytest.mark.asyncio
async def test_session_send_nonzero_exit(monkeypatch: pytest.MonkeyPatch):
    """Test error response when CLI exits with non-zero status."""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=2, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    response = await ClaudeSession().send("Hello")
    assert response.is_error is True
    assert "error" in response.content.lower()
    assert "boom" in response.content


@pytest.mark.asyncio
async def test_session_send_missing_cli(monkeypatch: pytest.MonkeyPatch):
    """Test user-facing error when CLI is not installed."""

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    response = await ClaudeSession().send("Hello")
    assert response.is_error is True
    assert "not found" in response.content.lower()
