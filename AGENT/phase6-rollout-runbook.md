# Phase 6: Rollout and Rollback Runbook

## Date
- 2026-03-29

## Rollout Stages
1. **Opt-in**
   - Set `FEISHU_BACKEND=codex` in target environment.
   - Keep rollback switch available: `FEISHU_BACKEND=claude`.
   - Validate `/status`, `/tools`, `/mode`, `/budget`, `/turns` in a pilot chat.
2. **Default-on**
   - Use default config (`FEISHU_BACKEND` unset -> `codex`).
   - Monitor logs:
     - `codex_run ...`
     - `policy_preflight ...`
     - `safety_gate ...`
   - Watch for policy-block spikes or repeated risk-confirmation prompts.
3. **Legacy deprecation window**
   - Keep `claude` as rollback-only path.
   - Communicate deprecation notice to operators.
   - Remove rollback path only after dedicated follow-up approval.

## Rollback Procedure
1. Set `FEISHU_BACKEND=claude`.
2. Restart bot process.
3. Run `/status` and verify:
   - `Backend: claude`
   - `Backend note: rollback-only (deprecated)`
4. Run smoke message flow in Feishu and confirm replies.

## Operator Checklist
- [ ] Environment vars validated (`FEISHU_APP_ID`, `FEISHU_APP_SECRET`).
- [ ] `codex` CLI available in runtime PATH.
- [ ] Optional `CODEX_EXECPOLICY_RULES` files present/readable.
- [ ] Guardrail defaults configured (`FEISHU_DEFAULT_TURN_LIMIT`, `FEISHU_DEFAULT_BUDGET_USD`) if required.
- [ ] Regression tests pass before deployment.

## Known Constraints
- Webhook transport remains unimplemented (`long_connection` only runtime path).
- In-memory state only; session controls are process-lifecycle scoped.
