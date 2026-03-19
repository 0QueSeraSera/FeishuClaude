"""Claude Code CLI integration."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClaudeResponse:
    """Response from Claude Code CLI."""

    content: str
    session_id: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    is_error: bool = False
    raw_output: str = ""


@dataclass
class ClaudeSession:
    """Manages a Claude Code session for a specific chat."""

    session_id: str | None = None
    workspace: Path = field(default_factory=Path.cwd)
    model: str | None = None
    max_turns: int | None = None

    def build_args(self, prompt: str, continue_session: bool = False) -> list[str]:
        """Build CLI arguments for Claude Code."""
        args = ["claude", "--print"]

        if continue_session and self.session_id:
            args.extend(["--resume", self.session_id])
        elif continue_session:
            args.append("--continue")

        if self.model:
            args.extend(["--model", self.model])

        if self.max_turns:
            args.extend(["--max-turns", str(self.max_turns)])

        # Skip permission prompts for bot usage
        args.append("--dangerously-skip-permissions")

        # Add the prompt
        args.append(prompt)

        return args

    async def send(self, prompt: str, continue_session: bool = True) -> ClaudeResponse:
        """Send a message to Claude Code and get response."""
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
                    content=f"Claude Code error: {error_output or raw_output}",
                    is_error=True,
                    raw_output=raw_output,
                )

            # Try to extract session ID from output if available
            # Claude Code may output session info in certain modes
            return ClaudeResponse(
                content=raw_output,
                raw_output=raw_output,
            )

        except FileNotFoundError:
            return ClaudeResponse(
                content="Error: Claude Code CLI not found. Please install it first.",
                is_error=True,
            )
        except Exception as e:
            return ClaudeResponse(
                content=f"Error running Claude Code: {e}",
                is_error=True,
            )


class ClaudeRunner:
    """Manages Claude Code sessions for multiple chats."""

    def __init__(
        self,
        workspace: Path = Path.cwd(),
        model: str | None = None,
        max_turns: int | None = None,
    ):
        self.workspace = workspace
        self.model = model
        self.max_turns = max_turns
        self._sessions: dict[str, ClaudeSession] = {}

    @staticmethod
    def check_cli_available() -> tuple[bool, str]:
        """Check if Claude Code CLI is available."""
        claude_path = shutil.which("claude")
        if claude_path:
            return True, claude_path
        return False, "Claude Code CLI not found in PATH"

    def get_or_create_session(self, chat_id: str) -> ClaudeSession:
        """Get or create a Claude session for a chat."""
        if chat_id not in self._sessions:
            self._sessions[chat_id] = ClaudeSession(
                workspace=self.workspace,
                model=self.model,
                max_turns=self.max_turns,
            )
        return self._sessions[chat_id]

    def reset_session(self, chat_id: str) -> bool:
        """Reset a chat's session (start fresh conversation)."""
        if chat_id in self._sessions:
            del self._sessions[chat_id]
            return True
        return False

    def list_sessions(self) -> list[str]:
        """List all active session chat IDs."""
        return list(self._sessions.keys())

    async def send_message(
        self,
        chat_id: str,
        message: str,
        continue_session: bool = True,
    ) -> ClaudeResponse:
        """Send a message to Claude for a specific chat."""
        session = self.get_or_create_session(chat_id)
        return await session.send(message, continue_session)
