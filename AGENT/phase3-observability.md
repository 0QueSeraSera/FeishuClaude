# Phase 3: Observability and Feishu Response UX

## Date
- 2026-03-29

## Delivered
- Codex runner upgraded to stream and parse `codex exec --json` event lines.
- Added telemetry model (`CodexEventSummary`) with captured fields:
  - event_count
  - event_types
  - session_id
  - cost_usd
  - duration_ms
  - error
- Added Feishu staged response pattern for Codex:
  1. immediate ack (`已收到，处理中...`)
  2. threshold-based progress updates for long runs
  3. final response + compact footer
- Added structured log line with:
  - chat_id
  - mode
  - prompt hash
  - event_count
  - duration_ms
  - cost_usd
  - error flag

## Chinese-first UX
- Default language is Chinese via `FEISHU_DEFAULT_LANGUAGE=zh`.
- Footer style:
  - `模式: <mode> | 耗时: <sec>s | 事件: <n> | 估算成本: <usd>`

## Verification
- JSON parsing tests (success/error/partial): `tests/test_codex_runner.py`.
- Formatter + staged response E2E tests: `tests/test_e2e_observability.py`.

## Evidence
- Test output: `AGENT/phase3-pytest.txt`
