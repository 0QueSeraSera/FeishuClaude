# Phase 4: Safety Gates and Policy Preflight

## Date
- 2026-03-29

## Delivered
- Added rule-based risk intent detector (`RiskIntentDetector`) for destructive keywords.
- Added explicit confirmation flow in Feishu:
  - risky prompt -> bot requires `/confirm`
  - `/cancel` clears pending risky action
- Integrated optional `codex execpolicy check` preflight (`ExecPolicyChecker`).
- Added policy decision logging metadata (`allow|prompt|block|unknown`) with reason.
- Non-dangerous default remains `mode=safe` for new sessions.

## Runtime Behavior
- Risky prompt without confirmation: execution does not start.
- Policy `block`/`unknown`: execution is blocked with clear reason.
- Policy `prompt`: execution requires explicit `/confirm`.

## Verification
- Risk classifier tests: `tests/test_safety.py`.
- Policy integration tests: `tests/test_policy.py`.
- E2E safety and policy flows: `tests/test_e2e_safety_policy.py`.

## Evidence
- Test output: `AGENT/phase4-pytest.txt`
