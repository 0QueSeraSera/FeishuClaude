# FeishuClaude Enhancement Proposals

## Document Role and Source of Truth

This file is the decision and prioritization tracker.

Implementation details are canonical in:
- `AGENT/codex-feishu-scope-command-mapping.md`

If this file and the implementation spec disagree, follow:
- `AGENT/codex-feishu-scope-command-mapping.md`

---

## Current Limitations (Validated Against Current Code)

### 1. Limited Observability
Current runner uses simple text output and does not expose structured turn events to Feishu.

### 2. Unsafe Default Execution Pattern
Current backend path runs with dangerous permission bypass semantics, which is unsuitable as a default in Feishu group usage.

### 3. No Chat-Scoped Governance
Mode, policy, and safety controls are not yet first-class per-chat runtime settings.

### 4. No Budget/Turn Guardrails at Product Layer
There is no Feishu-side budget or turn ceiling to prevent runaway usage.

### 5. Transport Mismatch
`webhook` appears in config but runtime currently only implements long-connection behavior.

---

## Aligned Proposal Set (Codex-Centric)

## Proposal 1: Structured Observability via Codex JSON Events

**Decision**: Adopt `codex exec --json` telemetry as standard for runtime visibility.

**Why**:
- machine-readable event stream for logging and auditing
- easier progress updates in Feishu
- stable base for future analytics

**Canonical details**:
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Observability Contract`

---

## Proposal 2: Safety by Sandbox + Approvals + Policy Checks

**Decision**: Replace tool allow/deny style controls with Codex-native controls:
- sandbox level
- approval mode
- optional `execpolicy` preflight checks

**Why**:
- lower accidental risk than global bypass
- clearer operator mental model
- better fit for Feishu group workflows

**Canonical details**:
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Session Modes`
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Safety and Risk Controls`

---

## Proposal 3: Feishu Chat Commands as Control Plane

**Decision**: Expose per-chat controls through explicit commands (`/mode`, `/model`, `/search`, `/tools`, `/budget`, `/turns`, etc.).

**Why**:
- users control risk and behavior from the same chat thread
- fewer hidden runtime assumptions
- easier operations and support

**Canonical details**:
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Feishu Command Surface`
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Feishu Command -> Codex CLI Mapping`

---

## Proposal 4: Feishu-First Defaults (Chinese IM)

**Decision**:
- default mode: `safe`
- concise Chinese response style
- explicit mention-gating behavior in groups
- immediate ack + compact final footer pattern

**Why**:
- aligns with Chinese enterprise IM expectations
- reduces group chat noise and accidental execution

**Canonical details**:
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Default Operating Pattern (Feishu-first)`

---

## Proposal 5: Backend Migration Strategy

**Decision**: Support migration window with optional backend switch, then make Codex default.

**Why**:
- lowers rollout risk
- allows A/B comparison and fallback during early rollout

**Canonical details**:
- `AGENT/codex-feishu-scope-command-mapping.md` -> `Rollout Plan`

---

## Conflict Resolution Matrix (Old -> New)

| Old statement | Status | Aligned replacement |
|---|---|---|
| `claude --output-format stream-json` as primary path | Replaced | `codex exec --json` |
| tool whitelist/blacklist as core safety model | Replaced | sandbox + approvals + optional `execpolicy` |
| `/safe` as separate toggle command | Consolidated | `/mode safe` |
| plan mode as only safe-review option | Adjusted | read-only safe mode + explicit confirmation flow |
| Claude-only references as implementation baseline | Replaced | Codex-centric mapping spec |

---

## Implementation Priority (Aligned)

1. **High**: Codex JSON telemetry integration
2. **High**: Session modes and command mapping (`/mode`, `/tools`, `/search`)
3. **High**: Risk controls (confirmation gate + policy preflight)
4. **Medium**: Budget and turn limits at Feishu product layer
5. **Medium**: Backend migration switch and deprecation path
6. **Low**: Interactive approval UX and richer bidirectional workflows

---

## Open Items

- Implement webhook mode or remove it from runtime config until supported.
- Define persistent session storage strategy if `/resume` and `/fork` must survive process restarts.
- Confirm final budget metric source and unit strategy for user-facing reporting.

---

## References

- `AGENT/codex-feishu-scope-command-mapping.md`
- [Codex CLI overview](https://developers.openai.com/codex/cli)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
