"""Tests for Codex runner."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from feishu_claude.codex_runner import CodexRunner, CodexSession


class _FakeProcess:
    """Minimal fake process for subprocess tests."""

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes):
        self.returncode = returncode
        self.stdout = _FakeStream(stdout)
        self.stderr = _FakeStream(stderr)

    async def wait(self) -> int:
        """Return preconfigured process exit code."""
        return self.returncode


class _FakeStream:
    """Minimal stream object with readline/read APIs."""

    def __init__(self, payload: bytes):
        self._lines = payload.splitlines(keepends=True)
        self._line_index = 0
        self._payload = payload
        self._read_used = False

    async def readline(self) -> bytes:
        """Read one line from stream payload."""
        if self._line_index >= len(self._lines):
            return b""
        line = self._lines[self._line_index]
        self._line_index += 1
        return line

    async def read(self) -> bytes:
        """Read remaining stream payload."""
        if self._read_used:
            return b""
        self._read_used = True
        return self._payload


def test_codex_session_build_args():
    """Codex runner should build expected CLI args."""
    session = CodexSession(workspace=Path("/tmp/workspace"))

    args = session.build_args("read project", continue_session=False)
    assert args[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "--json" in args
    assert "--cd" in args
    assert "read-only" in args
    assert "never" in args

    session.mode = "normal"
    args = session.build_args("do change", continue_session=False)
    assert "workspace-write" in args
    assert "on-request" in args

    session.mode = "full"
    args = session.build_args("do risky thing", continue_session=False)
    assert "--dangerously-bypass-approvals-and-sandbox" in args

    session.model = "gpt-5-codex"
    session.search_enabled = True
    args = session.build_args("search docs", continue_session=False)
    assert "--model" in args
    assert "gpt-5-codex" in args
    assert "--search" in args


def test_codex_args_snapshot_for_normal_mode():
    """Snapshot-like test for canonical command mapping."""
    session = CodexSession(
        workspace=Path("/repo"),
        mode="normal",
        model="gpt-5-codex",
        search_enabled=True,
    )
    args = session.build_args("fix bug", continue_session=False)
    assert args == [
        "codex",
        "--ask-for-approval",
        "on-request",
        "exec",
        "fix bug",
        "--cd",
        "/repo",
        "--json",
        "--sandbox",
        "workspace-write",
        "--model",
        "gpt-5-codex",
        "--search",
    ]


def test_codex_check_cli_available(monkeypatch: pytest.MonkeyPatch):
    """CLI availability checks should map to shutil.which results."""
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/codex")
    available, info = CodexRunner.check_cli_available()
    assert available is True
    assert "codex" in info

    monkeypatch.setattr(shutil, "which", lambda _: None)
    available, info = CodexRunner.check_cli_available()
    assert available is False
    assert "not found" in info.lower()


@pytest.mark.asyncio
async def test_codex_send_message_success(monkeypatch: pytest.MonkeyPatch):
    """Runner should parse JSONL output and return final message."""
    expected_workspace = Path("/tmp/codex")

    stdout = (
        '{"type":"run.started","session_id":"ses_1"}\n'
        '{"type":"message","text":"Hello from Codex"}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert args[0] == "codex"
        assert kwargs["cwd"] == str(expected_workspace)
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    runner = CodexRunner(workspace=expected_workspace)
    response = await runner.send_message("chat_1", "hello")
    assert response.is_error is False
    assert response.content == "Hello from Codex"
    assert response.session_id == "ses_1"
    assert response.event_count == 2


@pytest.mark.asyncio
async def test_codex_send_message_partial_events(monkeypatch: pytest.MonkeyPatch):
    """Runner should merge delta events and capture telemetry fields."""
    expected_workspace = Path("/tmp/codex")
    stdout = (
        '{"type":"run.started","session_id":"ses_partial"}\n'
        '{"type":"message.delta","delta":"Hello "}\n'
        '{"type":"message.delta","delta":"world"}\n'
        '{"type":"run.completed","usage":{"total_cost_usd":0.015},"duration_ms":2300}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert kwargs["cwd"] == str(expected_workspace)
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner(workspace=expected_workspace)
    response = await runner.send_message("chat_1", "hello")

    assert response.is_error is False
    assert response.content == "Hello world"
    assert response.cost_usd == 0.015
    assert response.duration_ms == 2300
    assert response.event_count == 4


@pytest.mark.asyncio
async def test_codex_send_message_progress_callback(monkeypatch: pytest.MonkeyPatch):
    """Runner should call progress callback for each parsed JSON event."""
    stdout = (
        '{"type":"run.started","session_id":"ses_9"}\n'
        '{"type":"message","text":"Final"}\n'
    ).encode("utf-8")
    events: list[int] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    async def progress_callback(event_count, event, summary):
        del event, summary
        events.append(event_count)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_a", "hello", progress_callback=progress_callback)

    assert response.is_error is False
    assert events == [1, 2]


@pytest.mark.asyncio
async def test_codex_send_message_error(monkeypatch: pytest.MonkeyPatch):
    """Runner should return error details on non-zero exit."""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=1, stdout=b"", stderr=b"permission denied")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_1", "hello")
    assert response.is_error is True
    assert "permission denied" in response.content


@pytest.mark.asyncio
async def test_codex_send_message_parses_nested_response_payload(monkeypatch: pytest.MonkeyPatch):
    """Runner should extract final text from nested response-completed schema."""
    stdout = (
        '{"type":"turn.started"}\n'
        '{"type":"response.completed","response":{"output":[{"type":"message","role":"assistant",'
        '"content":[{"type":"output_text","text":"Nested hello"}]}]}}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_nested", "hello")

    assert response.is_error is False
    assert response.content == "Nested hello"


@pytest.mark.asyncio
async def test_codex_send_message_parses_item_completed_assistant_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    """Runner should extract assistant text from item-completed event payloads."""
    stdout = (
        '{"type":"turn.started"}\n'
        '{"type":"item.completed","item":{"type":"message","role":"assistant",'
        '"content":[{"type":"output_text","text":"Item hello"}]}}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_item", "hello")

    assert response.is_error is False
    assert response.content == "Item hello"


@pytest.mark.asyncio
async def test_codex_send_message_reads_output_last_message_file(
    monkeypatch: pytest.MonkeyPatch,
):
    """Runner should fallback to output-last-message file when JSON has no final text."""
    stdout = (
        '{"type":"thread.started","thread_id":"th_1"}\n'
        '{"type":"turn.completed"}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        args_list = list(args)
        output_flag_index = args_list.index("--output-last-message")
        output_path = Path(args_list[output_flag_index + 1])
        output_path.write_text("Final from file", encoding="utf-8")
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_file", "hello")

    assert response.is_error is False
    assert response.content == "Final from file"


@pytest.mark.asyncio
async def test_codex_send_message_uses_friendly_fallback_when_no_final_text(
    monkeypatch: pytest.MonkeyPatch,
):
    """Runner should never expose raw JSONL output as user-facing final content."""
    stdout = (
        '{"type":"thread.started","thread_id":"th_1"}\n'
        '{"type":"turn.completed"}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_empty", "hello")

    assert response.is_error is False
    assert response.content == "Codex run completed without a final assistant message."
    assert '{"type":"thread.started"' in response.raw_output


@pytest.mark.asyncio
async def test_codex_send_message_ignores_tool_metadata_as_final_text(
    monkeypatch: pytest.MonkeyPatch,
):
    """Tool lifecycle metadata should not be promoted to final assistant content."""
    stdout = (
        '{"type":"tool.call.started","tool_name":"exec_command","message":"running"}\n'
        '{"type":"tool.call.completed","tool_name":"exec_command","message":"exit_code=0"}\n'
    ).encode("utf-8")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = CodexRunner()
    response = await runner.send_message("chat_tool_only", "hello")

    assert response.is_error is False
    assert response.content == "Codex run completed without a final assistant message."
