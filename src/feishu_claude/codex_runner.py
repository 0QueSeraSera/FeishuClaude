"""Codex CLI integration with JSON event streaming support."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from .claude_runner import ClaudeResponse

ExecutionMode = Literal["safe", "normal", "full"]
MODE_FLAG_MAP: dict[ExecutionMode, tuple[str, ...]] = {
    "safe": ("--sandbox", "read-only", "--ask-for-approval", "never"),
    "normal": ("--sandbox", "workspace-write", "--ask-for-approval", "on-request"),
    "full": ("--dangerously-bypass-approvals-and-sandbox",),
}
ProgressCallback = Callable[[int, dict[str, Any], "CodexEventSummary"], Awaitable[None] | None]


@dataclass
class CodexEventSummary:
    """Tracks structured run telemetry derived from Codex JSON events."""

    event_count: int = 0
    event_types: list[str] = field(default_factory=list)
    session_id: str | None = None
    final_text: str = ""
    _text_chunks: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None

    def update_from_event(self, event: dict[str, Any]) -> None:
        """Update telemetry state from one parsed event line.

        Args:
            event: Parsed JSON event object emitted by Codex.
        """
        self.event_count += 1
        event_type = _extract_event_type(event)
        if event_type:
            self.event_types.append(event_type)

        session_id = _extract_session_id(event)
        if session_id:
            self.session_id = session_id

        full_text = _extract_full_text(event)
        if full_text:
            self.final_text = full_text

        delta = _extract_delta_text(event)
        if delta:
            self._text_chunks.append(delta)

        event_cost = _extract_cost_usd(event)
        if event_cost is not None:
            self.cost_usd = event_cost

        event_duration = _extract_duration_ms(event)
        if event_duration is not None:
            self.duration_ms = event_duration

        event_error = _extract_error_text(event)
        if event_error:
            self.error = event_error

    def ingest_non_json_line(self, line: str) -> None:
        """Handle non-JSON stdout line as best-effort text."""
        stripped = line.strip()
        if stripped:
            self.final_text = stripped

    def resolved_final_text(self) -> str:
        """Resolve final text from full messages or delta chunks."""
        if self.final_text:
            return self.final_text.strip()
        if self._text_chunks:
            return "".join(self._text_chunks).strip()
        return ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize telemetry for logging and diagnostics."""
        return {
            "event_count": self.event_count,
            "event_types": self.event_types,
            "session_id": self.session_id,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class CodexSession:
    """Manages a Codex session for a specific chat."""

    session_id: str | None = None
    workspace: Path = field(default_factory=Path.cwd)
    model: str | None = None
    search_enabled: bool = False
    mode: ExecutionMode = "safe"

    def build_args(self, prompt: str, continue_session: bool = False) -> list[str]:
        """Build CLI arguments for Codex.

        Args:
            prompt: User prompt to pass into `codex exec`.
            continue_session: Whether to resume an existing session when possible.

        Returns:
            List of command arguments for subprocess execution.
        """
        global_flags, exec_flags = _split_mode_flags(MODE_FLAG_MAP[self.mode])
        args = ["codex", *global_flags, "exec"]
        if continue_session and self.session_id:
            args.extend(["resume", self.session_id, prompt])
        else:
            args.append(prompt)

        args.extend(["--cd", str(self.workspace), "--json"])
        args.extend(exec_flags)

        if self.model:
            args.extend(["--model", self.model])
        if self.search_enabled:
            args.append("--search")

        return args

    async def send(
        self,
        prompt: str,
        continue_session: bool = True,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> ClaudeResponse:
        """Send a message to Codex CLI and return normalized response.

        Args:
            prompt: User prompt text.
            continue_session: Resume previously tracked session when available.
            progress_callback: Optional callback invoked for each parsed event.

        Returns:
            Bot-compatible response object with telemetry and final text.
        """
        args = self.build_args(prompt, continue_session)
        start_monotonic = time.monotonic()
        summary = CodexEventSummary()
        raw_lines: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            if process.stdout is None or process.stderr is None:
                raise RuntimeError("Codex process stdout/stderr is unavailable")

            stderr_task = asyncio.create_task(process.stderr.read())

            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                raw_lines.append(line)
                event = _parse_json_event(line)
                if event is None:
                    summary.ingest_non_json_line(line)
                    continue

                summary.update_from_event(event)
                if progress_callback is not None:
                    maybe_coro = progress_callback(summary.event_count, event, summary)
                    if asyncio.iscoroutine(maybe_coro):
                        await maybe_coro

            return_code = await process.wait()
            stderr_output = (await stderr_task).decode("utf-8", errors="replace").strip()
            elapsed_ms = int((time.monotonic() - start_monotonic) * 1000)
            if summary.duration_ms is None:
                summary.duration_ms = elapsed_ms

            raw_output = "\n".join(raw_lines).strip()

            if return_code != 0:
                error_text = stderr_output or summary.error or summary.resolved_final_text()
                if not error_text:
                    error_text = "Codex execution failed with unknown error."
                return ClaudeResponse(
                    content=f"Codex error: {error_text}",
                    is_error=True,
                    raw_output=raw_output,
                    event_count=summary.event_count,
                    duration_ms=summary.duration_ms,
                    telemetry=summary.to_dict(),
                )

            if summary.session_id:
                self.session_id = summary.session_id

            final_text = summary.resolved_final_text() or raw_output
            return ClaudeResponse(
                content=final_text,
                session_id=self.session_id,
                cost_usd=summary.cost_usd,
                duration_ms=summary.duration_ms,
                raw_output=raw_output,
                event_count=summary.event_count,
                telemetry=summary.to_dict(),
            )

        except FileNotFoundError:
            return ClaudeResponse(
                content="Error: Codex CLI not found. Please install it first.",
                is_error=True,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return ClaudeResponse(
                content=f"Error running Codex: {exc}",
                is_error=True,
            )


class CodexRunner:
    """Manages Codex sessions for multiple chats."""

    def __init__(
        self,
        workspace: Path = Path.cwd(),
        model: str | None = None,
        search_enabled: bool = False,
        mode: ExecutionMode = "safe",
    ):
        """Initialize the runner.

        Args:
            workspace: Root workspace used for Codex `--cd`.
            model: Optional model override.
            search_enabled: Whether web search is enabled by default.
            mode: Default execution mode for newly created chat sessions.
        """
        self.workspace = workspace
        self.model = model
        self.search_enabled = search_enabled
        self.mode = mode
        self._sessions: dict[str, CodexSession] = {}

    @staticmethod
    def check_cli_available() -> tuple[bool, str]:
        """Check whether Codex CLI is available in PATH."""
        codex_path = shutil.which("codex")
        if codex_path:
            return True, codex_path
        return False, "Codex CLI not found in PATH"

    def get_or_create_session(self, chat_id: str) -> CodexSession:
        """Return an existing chat session or create one."""
        if chat_id not in self._sessions:
            self._sessions[chat_id] = CodexSession(
                workspace=self.workspace,
                model=self.model,
                search_enabled=self.search_enabled,
                mode=self.mode,
            )
        return self._sessions[chat_id]

    def reset_session(self, chat_id: str) -> bool:
        """Reset session for a chat."""
        if chat_id in self._sessions:
            del self._sessions[chat_id]
            return True
        return False

    def list_sessions(self) -> list[str]:
        """List active chat ids with sessions."""
        return list(self._sessions.keys())

    async def send_message(
        self,
        chat_id: str,
        message: str,
        continue_session: bool = True,
        *,
        mode: ExecutionMode | None = None,
        model: str | None = None,
        search_enabled: bool | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ClaudeResponse:
        """Send a message to Codex for a specific chat.

        Args:
            chat_id: Feishu chat identifier.
            message: User prompt text.
            continue_session: Whether to continue previous session for this chat.
            mode: Optional runtime mode override.
            model: Optional runtime model override.
            search_enabled: Optional runtime search toggle override.
            progress_callback: Optional callback invoked for each parsed event.

        Returns:
            Runner response for the bot orchestration layer.
        """
        session = self.get_or_create_session(chat_id)
        if mode is not None:
            session.mode = mode
        if model is not None:
            session.model = model
        if search_enabled is not None:
            session.search_enabled = search_enabled
        return await session.send(
            message,
            continue_session,
            progress_callback=progress_callback,
        )


def _parse_json_event(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line into an event dict."""
    line = line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _split_mode_flags(mode_flags: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Split mode flags into root-level and `exec`-level argument groups.

    Args:
        mode_flags: Mode mapping tuple from `MODE_FLAG_MAP`.

    Returns:
        A tuple of `(global_flags, exec_flags)`.
    """
    remaining = list(mode_flags)
    global_flags: list[str] = []
    ask_flag = "--ask-for-approval"
    if ask_flag in remaining:
        idx = remaining.index(ask_flag)
        if idx + 1 < len(remaining):
            global_flags.extend([ask_flag, remaining[idx + 1]])
            del remaining[idx:idx + 2]
    return global_flags, remaining


def _extract_event_type(event: dict[str, Any]) -> str | None:
    """Extract event type identifier."""
    event_type = event.get("type")
    if isinstance(event_type, str) and event_type.strip():
        return event_type.strip()
    return None


def _extract_session_id(event: dict[str, Any]) -> str | None:
    """Extract session id from a Codex event if present."""
    sid = event.get("session_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()

    session = event.get("session")
    if isinstance(session, dict):
        nested = session.get("id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def _extract_full_text(event: dict[str, Any]) -> str:
    """Extract full assistant text from event payload."""
    direct_keys = ("final_message", "text")
    for key in direct_keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    message = event.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            combined = "".join(parts).strip()
            if combined:
                return combined

    content = event.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return ""


def _extract_delta_text(event: dict[str, Any]) -> str:
    """Extract incremental text chunk from event payload."""
    delta = event.get("delta")
    if isinstance(delta, str) and delta:
        return delta

    data = event.get("data")
    if isinstance(data, dict):
        nested_delta = data.get("delta")
        if isinstance(nested_delta, str) and nested_delta:
            return nested_delta
    return ""


def _extract_cost_usd(event: dict[str, Any]) -> float | None:
    """Extract cost estimate from one event."""
    candidates: list[Any] = [
        event.get("cost_usd"),
        event.get("total_cost_usd"),
    ]
    usage = event.get("usage")
    if isinstance(usage, dict):
        candidates.extend([usage.get("cost_usd"), usage.get("total_cost_usd")])

    for value in candidates:
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _extract_duration_ms(event: dict[str, Any]) -> int | None:
    """Extract duration in milliseconds from one event."""
    duration = event.get("duration_ms")
    if isinstance(duration, int):
        return duration

    metrics = event.get("metrics")
    if isinstance(metrics, dict):
        nested = metrics.get("duration_ms")
        if isinstance(nested, int):
            return nested
    return None


def _extract_error_text(event: dict[str, Any]) -> str | None:
    """Extract error text from a failed event."""
    event_type = _extract_event_type(event) or ""
    if "error" not in event_type.lower() and "error" not in event:
        return None

    error = event.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    message = event.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "unknown error"
