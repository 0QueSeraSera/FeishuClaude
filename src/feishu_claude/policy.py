"""Optional `codex execpolicy` preflight integration."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

PolicyDecisionType = Literal["allow", "prompt", "block", "unknown"]


@dataclass
class PolicyDecision:
    """Represents one policy preflight decision."""

    decision: PolicyDecisionType
    reason: str
    raw_output: str = ""


class ExecPolicyChecker:
    """Runs optional policy preflight checks using `codex execpolicy check`."""

    def __init__(self, rules: list[Path] | None = None):
        """Initialize checker with optional rule files.

        Args:
            rules: Paths to execpolicy rule files. Empty list disables checks.
        """
        self.rules = [rule for rule in (rules or []) if str(rule).strip()]

    @property
    def enabled(self) -> bool:
        """Whether policy preflight is enabled."""
        return bool(self.rules)

    async def check(self, prompt: str) -> PolicyDecision:
        """Evaluate prompt command text against configured policy rules.

        Args:
            prompt: Prompt text to be represented as a command payload for policy check.

        Returns:
            PolicyDecision object.
        """
        if not self.enabled:
            return PolicyDecision(decision="allow", reason="execpolicy disabled")

        args: list[str] = ["codex", "execpolicy", "check"]
        for rule in self.rules:
            args.extend(["--rules", str(rule)])
        # Execpolicy expects command argv; pass prompt through shell form for rule matching.
        args.extend(["--", "sh", "-lc", prompt])

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            error_output = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                reason = error_output or output or "execpolicy check failed"
                return PolicyDecision(decision="block", reason=reason, raw_output=output)

            parsed = _parse_policy_output(output)
            if parsed is not None:
                return parsed

            return PolicyDecision(
                decision="unknown",
                reason="execpolicy output was not valid JSON",
                raw_output=output,
            )
        except FileNotFoundError:
            return PolicyDecision(decision="block", reason="codex CLI not found for execpolicy check")
        except Exception as exc:  # pragma: no cover - defensive fallback
            return PolicyDecision(decision="block", reason=f"execpolicy check failed: {exc}")


def _parse_policy_output(output: str) -> PolicyDecision | None:
    """Parse `codex execpolicy` JSON output into a normalized decision."""
    if not output:
        return None

    payload: dict[str, Any] | None = None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break

    if payload is None:
        return None

    decision_raw = (
        payload.get("decision")
        or payload.get("strictest_decision")
        or payload.get("result")
        or payload.get("action")
    )
    reason = payload.get("reason") or payload.get("message") or "execpolicy decision available"

    if isinstance(decision_raw, str):
        decision = decision_raw.strip().lower()
        if decision in {"allow", "prompt", "block"}:
            return PolicyDecision(decision=decision, reason=str(reason), raw_output=output)

    return PolicyDecision(decision="unknown", reason=str(reason), raw_output=output)
