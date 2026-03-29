# Phase 0 Baseline: Behavior and Harness

## Date
- 2026-03-29

## Scope Captured
- Feishu message ingress via long-connection adapter.
- Bot command path (`/help`, `/new`, `/sessions`, `/status`, `/ping`).
- Default non-command message path: bot forwards to Claude runner and relays response.

## Repeatable Local Run
1. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
2. Configure `.env` with `FEISHU_APP_ID` and `FEISHU_APP_SECRET`.
3. Run startup checks:
   ```bash
   feishu-claude --once
   ```
4. Run full tests:
   ```bash
   pytest -q
   ```

## Baseline Message Flow
1. User sends Feishu message.
2. Adapter parses event and builds `FeishuMessage`.
3. Bot command parser checks for built-in command.
4. Non-command text is sent to runner.
5. Runner response is posted back to chat.

## Expected Command Responses
- `/help`: command list text.
- `/new`: resets current chat session.
- `/sessions`: lists in-memory active sessions.
- `/status`: prints CLI availability and workspace/model/session count.
- `/ping`: returns `pong 🏓`.

## Baseline E2E (In-Process) Evidence
- `tests/test_e2e_baseline.py`
  - `test_e2e_p2p_message_to_reply`
  - `test_e2e_group_message_to_reply`
