"""Per-chat runtime state for Feishu control-plane commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .codex_runner import MODE_FLAG_MAP, ExecutionMode

BackendType = Literal["claude", "codex"]
LanguageType = Literal["zh", "en"]


@dataclass
class ChatRuntimeState:
    """Stores chat-scoped runtime controls and guardrails.

    Attributes:
        backend: Selected backend for this chat.
        mode: Execution mode for Codex runs.
        model: Optional model override.
        search_enabled: Whether web search is enabled.
        language: Preferred bot response language.
        turn_limit: Optional per-chat turn limit.
        turns_used: Number of turns consumed so far.
        budget_limit_usd: Optional per-chat budget limit in USD.
        budget_used_usd: Accumulated spend estimate in USD.
        pending_confirmation_prompt: Cached prompt waiting explicit confirmation.
        pending_confirmation_reason: Human-readable reason for confirmation requirement.
    """

    backend: BackendType
    mode: ExecutionMode = "safe"
    model: str | None = None
    search_enabled: bool = False
    language: LanguageType = "zh"
    turn_limit: int | None = None
    turns_used: int = 0
    budget_limit_usd: float | None = None
    budget_used_usd: float = 0.0
    pending_confirmation_prompt: str | None = None
    pending_confirmation_reason: str | None = None

    def mode_flags_text(self) -> str:
        """Return mode-mapped Codex flags as a human-readable string."""
        return " ".join(MODE_FLAG_MAP[self.mode])

    def effective_model(self, backend_default_model: str | None) -> str | None:
        """Return runtime model with per-chat override precedence.

        Args:
            backend_default_model: Default model configured for selected backend.

        Returns:
            Effective model string or None when default model should be used.
        """
        return self.model if self.model else backend_default_model
