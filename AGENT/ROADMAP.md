# FeishuClaude Codex Roadmap

## Purpose

This roadmap defines implementation phases for enabling Codex in FeishuClaude with explicit, verifiable milestones.

Related documents:
- `AGENT/enhancement-proposals.md` (decision and priority tracker)
- `AGENT/codex-feishu-scope-command-mapping.md` (implementation source of truth)

If documents conflict on implementation behavior, follow:
- `AGENT/codex-feishu-scope-command-mapping.md`

---

## Delivery Principles

- Every phase must include E2E verification (not unit tests alone).
- No phase is complete without evidence artifacts.
- Default to safe behavior in Feishu group scenarios.
- Keep migration reversible until final default switch.

---

## Phase 0 - Baseline and Test Harness

## Objective
Establish reliable baseline behavior before introducing Codex backend changes.

## Scope
- Freeze current behavior of Feishu message flow and command handling.
- Confirm baseline tests and add missing coverage for current runner contract.
- Capture baseline operational logs for comparison.

## Deliverables
- Baseline test report (`pytest` output).
- Baseline behavior note under `AGENT/` (message flow + expected command responses).
- Repeatable local run instructions.

## Verification
- Automated:
  - `pytest` passes on clean environment.
- E2E:
  - Feishu p2p message -> bot reply success.
  - Group mention path (if enabled) -> bot reply success.

## Exit Criteria
- Baseline is reproducible by another engineer from clean checkout.

---

## Phase 1 - Introduce Codex Runner (Minimal Path)

## Objective
Add Codex backend execution path while preserving existing bot interface.

## Scope
- Implement `CodexRunner` with response contract compatible with existing bot flow.
- Add backend selector (`codex|claude`) for migration safety.
- Keep current command surface unchanged in this phase.

## Deliverables
- New runner module and tests.
- Backend configuration switch.
- Startup checks for Codex CLI availability.

## Verification
- Automated:
  - Runner argument-building unit tests.
  - Backend selection tests.
- E2E:
  - Same Feishu message returns valid reply when backend=`codex`.
  - Backend rollback to `claude` works without code change.

## Exit Criteria
- Codex path is functional and rollback path is verified.

---

## Phase 2 - Session Modes and Command Mapping

## Objective
Implement chat-scoped control commands and map them to Codex CLI behavior.

## Scope
- Add per-chat runtime state for mode and execution options.
- Implement commands:
  - `/mode <safe|normal|full>`
  - `/model <name>`
  - `/search <on|off>`
  - `/tools`
- Apply mapping defined in `AGENT/codex-feishu-scope-command-mapping.md`.

## Deliverables
- Command handlers with validation and error messages.
- Runtime state model for per-chat configuration.
- Updated `/help` and `/status` output reflecting active backend/mode.

## Verification
- Automated:
  - Command parsing tests.
  - Mode transition and state persistence tests (in-process lifecycle).
  - CLI argument generation snapshot tests.
- E2E:
  - Switch mode in Feishu and verify effective behavior change.
  - Invalid command inputs return clear guidance.

## Exit Criteria
- Command mapping is deterministic and reflected in status output.

---

## Phase 3 - Observability and Feishu Response UX

## Objective
Provide structured runtime visibility and Feishu-first response pattern.

## Scope
- Parse and consume `codex exec --json` event stream.
- Add response stages:
  1. immediate ack
  2. optional progress updates for long runs
  3. final response with compact execution footer
- Use Chinese-first concise default style.

## Deliverables
- Event parser and telemetry model.
- Feishu formatter for ack/progress/final messages.
- Logging fields for audit and troubleshooting.

## Verification
- Automated:
  - JSON event parsing tests (success/error/partial).
  - Formatter tests for Chinese response templates.
- E2E:
  - Long-running task emits ack and final summary.
  - Failed task returns actionable error message with context.

## Exit Criteria
- Each run produces both user-facing summary and machine-readable telemetry.

---

## Phase 4 - Safety Gates and Policy Preflight

## Objective
Prevent silent risky execution and enforce governance controls.

## Scope
- Add explicit confirmation gate for high-risk intent categories.
- Integrate optional `execpolicy` preflight checks.
- Ensure non-dangerous defaults for new sessions.

## Deliverables
- Risk intent detector (initial rule-based version).
- Confirmation flow in Feishu for gated actions.
- Policy decision logging (allow/prompt/block metadata).

## Verification
- Automated:
  - Risk classifier test cases (destructive and non-destructive).
  - Policy integration tests for pass/fail cases.
- E2E:
  - Destructive request does not execute without explicit confirmation.
  - Policy-blocked command returns clear blocked reason.

## Exit Criteria
- High-risk operations cannot execute silently.

---

## Phase 5 - Budget and Turn Guardrails

## Objective
Add product-layer limits to prevent runaway cost and looping.

## Scope
- Implement commands:
  - `/budget <usd>`
  - `/turns <n>`
- Enforce per-chat ceilings at runner orchestration layer.
- Surface limits and remaining allowance in `/status`.

## Deliverables
- Guardrail manager for budget/turn enforcement.
- User-facing notifications on limit hit.
- Config defaults for deployment-level ceilings.

## Verification
- Automated:
  - Budget accounting and threshold tests.
  - Turn-limit enforcement tests.
- E2E:
  - Over-limit runs are stopped and user gets explicit reason.
  - Status reflects active limits correctly.

## Exit Criteria
- Runaway sessions are bounded by enforced limits.

---

## Phase 6 - Rollout, Default Switch, and Hardening

## Objective
Promote Codex to default backend with staged risk control.

## Scope
- Staged rollout:
  1. opt-in
  2. default-on with rollback switch
  3. legacy path deprecation
- Publish operator runbook and rollback procedures.
- Finalize documentation and acceptance evidence.

## Deliverables
- Rollout checklist and runbook.
- Migration notes and deprecation notice.
- Final acceptance report.

## Verification
- Automated:
  - Full regression suite pass.
- E2E:
  - Core user scenarios pass on default Codex backend.
  - Rollback switch validated in production-like environment.

## Exit Criteria
- Codex is default and stable; rollback remains available for defined window.

---

## Milestone Gate Template (Applies to Every Phase)

A phase is complete only when all checks pass:

- Implementation complete for declared scope.
- Automated tests pass.
- E2E scenarios pass.
- Docs updated (`AGENT/` references and behavior notes).
- Evidence recorded (test output, screenshots/log snippets, command transcripts).
- Rollback/fallback for phase validated (when applicable).

---

## Evidence Checklist

For each phase, store or link:
- test command and output summary
- E2E scenario steps and result
- config values used
- known issues and accepted risks
- go/no-go decision with date

---

## Dependency Order

Recommended implementation order:
1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6

Parallelization guidance:
- Phase 3 can begin after Phase 1 stabilizes.
- Phase 4 policy work can run in parallel with late Phase 3 formatting.
- Phase 5 guardrails should start after Phase 2 command framework is stable.

---

## Risks and Mitigations

- Risk: CLI behavior drift across Codex versions.
  - Mitigation: pin/test minimum supported version and add startup capability checks.
- Risk: group-chat noise from verbose updates.
  - Mitigation: mention-gating + compact progress policy.
- Risk: false positives in risk detector.
  - Mitigation: conservative initial rule set and iterative tuning with logs.
- Risk: migration regressions.
  - Mitigation: backend switch, staged rollout, explicit rollback criteria.

---

## Definition of Done (Program Level)

Program is complete when:
- Codex is default backend.
- Safety modes and command mapping work as specified.
- Observability and guardrails are active.
- E2E flows are validated and documented.
- Legacy dangerous default path is removed or fully deprecated.
