# Feishu + Codex Enablement Spec

## Objective

Define how FeishuClaude enables `codex` as the execution engine, including:
- feature scope
- Feishu command surface
- exact command-to-CLI mapping
- default operating pattern for Feishu (Chinese IM) usage

This document is implementation-oriented and scoped to the current codebase under `src/feishu_claude/`.

Companion document:
- `AGENT/enhancement-proposals.md` (decision and priority tracker)

Conflict rule:
- if proposal text and this spec differ, this spec is the implementation source of truth.

---

## Current Baseline

### What exists now
- Feishu long-connection message ingestion via `lark-oapi` WebSocket.
- Feishu message send via OpenAPI `im/v1/messages`.
- Per-chat in-memory session tracking (keyed by `chat_id`).
- Basic commands: `/help`, `/new`, `/sessions`, `/status`, `/ping`.
- AI backend is currently `claude --print ... --dangerously-skip-permissions`.

### Known gap
- `FEISHU_CONNECTION_MODE=webhook` is configurable, but webhook runtime path is not implemented yet.

---

## Scope

### In Scope
- Add Codex runner and make it default backend.
- Add Feishu commands for mode/safety/runtime controls.
- Emit structured run telemetry from Codex JSON events.
- Define safe defaults for Feishu chat and group workflows.
- Keep per-chat session lifecycle (`new`, `resume`, optional `fork`).

### Out of Scope (this phase)
- Full bidirectional approval UX (interactive human approval during a running turn).
- Persistent database-backed session storage.
- Multi-tenant workspace orchestration.
- Webhook transport implementation (tracked separately).

---

## Default Operating Pattern (Feishu-first)

Feishu is high-frequency and often group-based, so defaults prioritize safety and concise response behavior.

- Default mode: `safe`
- Default sandbox: `read-only`
- Default approval: `never` (in safe mode)
- Default output style: concise Chinese summary first, optional detail after
- Group chat rule: only respond when bot is explicitly mentioned
- Long tasks: send immediate ack, then progress snippets, then final summary

Recommended first ack text:
- `已收到，处理中...`

Recommended final footer:
- `模式: <mode> | 耗时: <sec>s | 事件: <n> | 估算成本: <usd>`

---

## Session Modes

| Mode | Intent | Codex flags |
|---|---|---|
| `safe` | Read/explain/analyze | `--sandbox read-only --ask-for-approval never --json` |
| `normal` | Standard development | `--sandbox workspace-write --ask-for-approval on-request --json` |
| `full` | Unrestricted in isolated env only | `--dangerously-bypass-approvals-and-sandbox --json` |

Notes:
- `full` must display explicit warning in Feishu before activation.
- `normal` should remain the max mode for most chats.

---

## Feishu Command Surface

## Core commands
- `/help`: list commands and mode descriptions.
- `/status`: show backend, mode, workspace, model, active session count.
- `/new`: reset chat session.
- `/sessions`: list active sessions.

## Codex control commands
- `/mode <safe|normal|full>`: switch execution mode for current chat.
- `/model <name>`: set model for current chat.
- `/search <on|off>`: toggle Codex web search for current chat.
- `/turns <n>`: set wrapper-side max turns for current chat.
- `/budget <usd>`: set wrapper-side max budget for current chat.
- `/tools`: show effective safety controls (sandbox, approvals, execpolicy files).
- `/resume [session_id|last]`: resume prior session (if session persistence exists).
- `/fork [session_id|last]`: fork session thread.
- `/lang <zh|en>`: preferred response language for the chat.

## Admin-only commands (optional)
- `/backend <codex|claude>`: temporary backend switch for migration window.
- `/reload`: reload policy/config file without process restart.

---

## Feishu Command -> Codex CLI Mapping

This table defines canonical argument mapping for non-interactive execution (`codex exec`).

| Feishu input | Codex invocation change |
|---|---|
| normal message | `codex exec "<prompt>"` + effective mode flags |
| `/mode safe` | add `--sandbox read-only --ask-for-approval never` |
| `/mode normal` | add `--sandbox workspace-write --ask-for-approval on-request` |
| `/mode full` | add `--dangerously-bypass-approvals-and-sandbox` |
| `/model gpt-5-codex` | add `--model gpt-5-codex` |
| `/search on` | add `--search` |
| `/search off` | omit `--search` |
| structured output required | add `--output-schema <path>` |
| machine-readable telemetry | add `--json` |
| persist final assistant text | add `--output-last-message <path>` |
| specific workspace | add `--cd <workspace>` |
| extra writable path | add `--add-dir <path>` (repeatable) |

Base execution template:

```bash
codex exec "<prompt>" \
  --cd "<workspace>" \
  --json \
  [mode flags...] \
  [model/search/options...]
```

---

## Safety and Risk Controls

## Required controls
- Never default to dangerous bypass mode.
- Enforce chat-scoped mode with explicit state.
- For destructive intent keywords (`delete`, `reset`, `drop`, `push --force`), require explicit user confirmation in Feishu before execution.

## Recommended controls
- Preflight checks with `codex execpolicy check` against configured rule files.
- Use `--add-dir` instead of `danger-full-access` whenever possible.
- Record decision metadata (mode, flags, rule outcome) in logs.

---

## Observability Contract

Use Codex JSON event stream as source of truth.

Minimum captured fields per turn:
- chat_id
- mode
- prompt hash (not raw prompt for sensitive contexts)
- command args (redacted secrets)
- start/end timestamp
- event count
- final message
- error (if any)

Feishu reply behavior:
1. Send quick ack.
2. Stream short progress updates for long tasks (optional threshold-based).
3. Send final answer with compact execution footer.

---

## Usage Examples (Feishu)

### Example 1: Safe analysis
1. User: `/mode safe`
2. User: `请阅读这个仓库并总结主要模块`
3. Bot runs Codex with read-only sandbox and returns Chinese summary.

### Example 2: Controlled code change
1. User: `/mode normal`
2. User: `在配置加载失败时返回更清晰错误`
3. Bot runs Codex workspace-write with on-request approval policy.

### Example 3: High-risk request
1. User: `删除历史分支并强推到 main`
2. Bot: asks explicit confirmation and blocks by default unless policy allows.

---

## Rollout Plan

1. Implement Codex runner alongside existing Claude runner behind backend switch.
2. Add `/mode`, `/model`, `/search`, `/tools`, `/budget`, `/turns`.
3. Enable JSON telemetry and Feishu progress formatting.
4. Make Codex default backend after verification.
5. Deprecate direct dangerous Claude execution path.

---

## Acceptance Criteria

- Bot can execute Codex in `safe` and `normal` modes from Feishu.
- Command mapping behaves as specified.
- Feishu responses include concise Chinese summary and execution footer.
- Risky actions are not executed silently.
- Existing commands (`/help`, `/new`, `/status`) continue to work.

