# Phase 5: Budget and Turn Guardrails

## Date
- 2026-03-29

## Delivered
- Added commands:
  - `/budget <usd|off>`
  - `/turns <n|off>`
- Enforced per-chat ceilings before backend execution.
- Added runtime usage accounting:
  - `turns_used`
  - `budget_used_usd`
- Updated `/status` and `/tools` to show active limits and usage.
- Added deployment-level defaults:
  - `FEISHU_DEFAULT_TURN_LIMIT`
  - `FEISHU_DEFAULT_BUDGET_USD`

## Runtime Behavior
- When turn limit is reached, execution is blocked with explicit reason.
- When budget limit is reached, execution is blocked with explicit reason.
- Usage accounting increments after each backend attempt.

## Verification
- Command/state tests: `tests/test_bot.py`.
- E2E limit enforcement and status reflection: `tests/test_e2e_guardrails.py`.

## Evidence
- Test output: `AGENT/phase5-pytest.txt`
