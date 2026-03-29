# Phase 1: Codex Runner Minimal Path

## Date
- 2026-03-29

## Delivered
- Added `CodexRunner` with `codex exec --json` invocation path.
- Added backend selector via `FEISHU_BACKEND` (`claude|codex`).
- Bot startup now validates selected backend CLI availability.
- `/status` now shows active backend and selected backend CLI status.

## Config Added
- `FEISHU_BACKEND` (default: `claude` in this phase)
- `CODEX_WORKSPACE`
- `CODEX_MODEL`
- `CODEX_SEARCH_ENABLED`
- `CODEX_DEFAULT_MODE`

## Verification
- Automated tests:
  - `tests/test_codex_runner.py`
  - `tests/test_e2e_backend_switch.py`
  - `tests/test_bot.py`
- E2E (in-process):
  - backend=`codex` routes message to Codex runner.
  - backend=`claude` rollback routes message to Claude runner without code changes.

## Evidence
- Test output: `AGENT/phase1-pytest.txt`
