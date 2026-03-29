"""Codex CLI integration."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .claude_runner import ClaudeResponse

ExecutionMode = Literal["safe", "normal", "full"]
MODE_FLAG_MAP: dict[ExecutionMode, tuple[str, ...]] = {
    "safe": ("--sandbox", "read-only", "--ask-for-approval", "never"),
    "normal": ("--sandbox", "workspace-write", "--ask-for-approval", "on-request"),
    "full": ("--dangerously-bypass-approvals-and-sandbox",),
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
        args = ["codex", "exec"]
        if continue_session and self.session_id:
            args.extend(["resume", self.session_id, prompt])
        else:
            args.append(prompt)

        args.extend(["--cd", str(self.workspace), "--json"])

        args.extend(MODE_FLAG_MAP[self.mode])

        if self.model:
            args.extend(["--model", self.model])

        if self.search_enabled:
            args.append("--search")

        return args

    async def send(self, prompt: str, continue_session: bool = True) -> ClaudeResponse:
        """Send a message to Codex CLI and return a normalized response.

        Args:
            prompt: User prompt text.
            continue_session: Resume previously tracked Codex session for this chat if present.

        Returns:
            ClaudeResponse-compatible payload used by bot orchestration.
        """
        args = self.build_args(prompt, continue_session)

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            raw_output = stdout.decode("utf-8", errors="replace").strip()
            error_output = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                return ClaudeResponse(
                    content=f"Codex error: {error_output or raw_output}",
                    is_error=True,
                    raw_output=raw_output,
                )

            final_text, session_id = _parse_codex_json_lines(raw_output)
            if session_id:
                self.session_id = session_id

            return ClaudeResponse(
                content=final_text or raw_output,
                session_id=self.session_id,
                raw_output=raw_output,
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
    ) -> ClaudeResponse:
        """Send a message to Codex for a specific chat.

        Args:
            chat_id: Feishu chat identifier.
            message: User prompt text.
            continue_session: Whether to continue previous session for this chat.
            mode: Optional runtime mode override.
            model: Optional runtime model override.
            search_enabled: Optional runtime search toggle override.

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
        return await session.send(message, continue_session)


def _parse_codex_json_lines(raw_output: str) -> tuple[str, str | None]:
    """Extract final assistant text and session id from Codex JSONL output.

    Args:
        raw_output: Raw stdout from `codex exec --json`.

    Returns:
        Tuple of `(final_text, session_id)`.
    """
    final_text = ""
    session_id: str | None = None
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Keep best-effort fallback for non-JSON output.
            final_text = line
            continue

        candidate = _extract_text(event)
        if candidate:
            final_text = candidate

        sid = _extract_session_id(event)
        if sid:
            session_id = sid

    return final_text, session_id


def _extract_text(event: dict[str, Any]) -> str:
    """Extract likely assistant message text from a Codex event."""
    direct_keys = ("final_message", "message", "content", "text", "delta")
    for key in direct_keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if isinstance(event.get("message"), dict):
        message = event["message"]
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text.strip())
            combined = "".join(parts).strip()
            if combined:
                return combined

    return ""


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
