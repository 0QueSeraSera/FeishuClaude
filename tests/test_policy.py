"""Tests for execpolicy preflight integration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from feishu_claude.policy import ExecPolicyChecker


class _FakeProcess:
    """Fake subprocess process used in policy tests."""

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return configured outputs."""
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_policy_checker_disabled():
    """When no rules are configured, checker should allow by default."""
    checker = ExecPolicyChecker([])
    decision = await checker.check("echo hello")
    assert decision.decision == "allow"


@pytest.mark.asyncio
async def test_policy_checker_parses_block(monkeypatch: pytest.MonkeyPatch):
    """Checker should parse block decision JSON output."""
    stdout = b'{"strictest_decision":"block","reason":"rm -rf denied"}\n'

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    checker = ExecPolicyChecker([Path("/tmp/rules.json")])
    decision = await checker.check("rm -rf /tmp/a")
    assert decision.decision == "block"
    assert "denied" in decision.reason


@pytest.mark.asyncio
async def test_policy_checker_subprocess_failure(monkeypatch: pytest.MonkeyPatch):
    """Checker should fail closed on subprocess errors."""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=2, stdout=b"", stderr=b"invalid rules")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    checker = ExecPolicyChecker([Path("/tmp/rules.json")])
    decision = await checker.check("echo hi")
    assert decision.decision == "block"
    assert "invalid rules" in decision.reason
