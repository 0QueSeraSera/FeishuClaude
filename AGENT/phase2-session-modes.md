# Phase 2: Session Modes and Command Mapping

## Date
- 2026-03-29

## Delivered
- Added per-chat runtime state model (`ChatRuntimeState`).
- Added commands:
  - `/mode <safe|normal|full>`
  - `/model <name|default>`
  - `/search <on|off>`
  - `/tools`
- Updated `/help` and `/status` to reflect backend/mode/search/model.
- Wired chat-scoped mode/model/search into Codex CLI invocation.

## Mapping Coverage
- `/mode safe` -> `--sandbox read-only --ask-for-approval never`
- `/mode normal` -> `--sandbox workspace-write --ask-for-approval on-request`
- `/mode full` -> `--dangerously-bypass-approvals-and-sandbox`
- `/model <name>` -> `--model <name>`
- `/search on` -> `--search`
- `/search off` -> omit `--search`
- `--json` remains enabled by default for telemetry path.

## Verification
- Command parsing tests in `tests/test_bot.py`.
- State persistence and runtime application in `tests/test_e2e_backend_switch.py`.
- CLI arg snapshot test in `tests/test_codex_runner.py::test_codex_args_snapshot_for_normal_mode`.

## Evidence
- Test output: `AGENT/phase2-pytest.txt`
