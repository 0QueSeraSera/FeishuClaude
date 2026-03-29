"""Safety helpers for risky intent detection in chat prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RiskAssessment:
    """Result of risky-intent classification for one prompt."""

    is_risky: bool
    matches: list[str]
    reason: str


class RiskIntentDetector:
    """Rule-based detector for potentially destructive user intents."""

    _PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("delete", re.compile(r"\b(delete|rm\s+-rf|remove)\b", re.IGNORECASE)),
        ("reset", re.compile(r"\b(reset|git\s+reset)\b", re.IGNORECASE)),
        ("drop", re.compile(r"\b(drop\s+table|drop\s+database|drop)\b", re.IGNORECASE)),
        ("force_push", re.compile(r"\b(push\s+--force|force\s+push)\b", re.IGNORECASE)),
        ("wipe", re.compile(r"(清空|删除|销毁|强推|格式化)", re.IGNORECASE)),
    )

    def assess(self, prompt: str) -> RiskAssessment:
        """Classify prompt risk level using deterministic keyword rules.

        Args:
            prompt: User prompt text.

        Returns:
            Structured assessment including matched categories and explanation.
        """
        text = prompt.strip()
        matches: list[str] = []
        for name, pattern in self._PATTERNS:
            if pattern.search(text):
                matches.append(name)

        if not matches:
            return RiskAssessment(is_risky=False, matches=[], reason="no risky keyword matched")

        match_text = ", ".join(matches)
        return RiskAssessment(
            is_risky=True,
            matches=matches,
            reason=f"detected risky intent keywords: {match_text}",
        )
