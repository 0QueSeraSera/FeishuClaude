# FeishuClaude

Connect Feishu bot to local Codex CLI (default) with Claude rollback support.

## Features

- **Real-time chat**: Receive and respond to Feishu messages via WebSocket (long-connection)
- **Codex default backend**: Use `codex exec --json` for structured execution
- **Rollback switch**: Set `FEISHU_BACKEND=claude` for temporary rollback
- **Session management**: Maintain conversation context per chat
- **Safety and guardrails**: Risk confirmation, policy preflight, budget, and turn limits

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -e .
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your Feishu app credentials
   ```

3. **Run startup checks**:
   ```bash
   feishu-claude --once
   ```

4. **Run the bot**:
   ```bash
   feishu-claude
   ```

## Enable Codex in `.env`

```env
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret
FEISHU_CONNECTION_MODE=long_connection
FEISHU_BACKEND=codex

# Optional Codex controls
CODEX_WORKSPACE=.
CODEX_MODEL=gpt-5.3-codex
CODEX_DEFAULT_MODE=safe
CODEX_SEARCH_ENABLED=false
# CODEX_EXECPOLICY_RULES=/path/to/rules-1.json,/path/to/rules-2.json
```

If you need temporary rollback, set:

```env
FEISHU_BACKEND=claude
```

## Configuration

### Feishu Bot Setup

1. Create a Feishu app at https://open.feishu.cn/app
2. Enable "Robot" capability
3. Configure event subscriptions (for webhook mode) or use long-connection mode
4. Get your `App ID` and `App Secret`

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `FEISHU_APP_ID` | Feishu app ID | Yes |
| `FEISHU_APP_SECRET` | Feishu app secret | Yes |
| `FEISHU_CONNECTION_MODE` | `long_connection` (`webhook` reserved, not implemented yet) | No (default: long_connection) |
| `FEISHU_BACKEND` | `claude` or `codex` | No (default: codex) |
| `FEISHU_ALLOW_USER_IDS` | Comma-separated allowed user IDs | No (allow all) |
| `FEISHU_ALLOW_GROUP_CHATS` | Allow group chats | No (default: true) |
| `FEISHU_DEFAULT_LANGUAGE` | Response language (`zh` or `en`) | No (default: `zh`) |
| `FEISHU_DEFAULT_TURN_LIMIT` | Default per-chat turn limit | No |
| `FEISHU_DEFAULT_BUDGET_USD` | Default per-chat budget limit (USD) | No |
| `CLAUDE_WORKSPACE` | Working directory for Claude | No (default: current dir) |
| `CODEX_WORKSPACE` | Working directory for Codex | No (default: CLAUDE_WORKSPACE) |
| `CODEX_MODEL` | Codex model override | No |
| `CODEX_DEFAULT_MODE` | Codex mode (`safe`, `normal`, `full`) | No (default: `safe`) |
| `CODEX_SEARCH_ENABLED` | Enable Codex web search by default | No (default: `false`) |
| `CODEX_EXECPOLICY_RULES` | Comma-separated execpolicy rule files | No |

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/new` | Start a new conversation session |
| `/sessions` | List all sessions |
| `/mode <safe\|normal\|full>` | Set Codex execution mode for current chat |
| `/model <name\|default>` | Set model override for current chat |
| `/search <on\|off>` | Toggle Codex web search |
| `/turns <n\|off>` | Set per-chat turn limit |
| `/budget <usd\|off>` | Set per-chat budget limit |
| `/tools` | Show effective safety controls |
| `/confirm` | Execute pending risky action |
| `/cancel` | Cancel pending risky action |
| `/status` | Show backend, mode, limits, and runtime status |

## Architecture

```
┌─────────────┐    WebSocket     ┌──────────────────┐
│  Feishu     │ ◄──────────────► │  FeishuAdapter   │
│  Server     │                  │  (lark-oapi)     │
└─────────────┘                  └────────┬─────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  Runtime State   │
                                 │  + Safety Gates  │
                                 └────────┬─────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  Codex / Claude  │
                                 │  CLI Runners     │
                                 └──────────────────┘
```

## How It Works

1. **Message Flow**:
   - Feishu user sends message to bot
   - FeishuAdapter receives via WebSocket
   - Runtime state and safety gates are evaluated
   - Message is sent to selected backend CLI
   - Response is sent back to Feishu

2. **Session Management**:
   - Each Feishu chat has its own backend session state
   - Sessions can be resumed across restarts
   - Use `/new` to start fresh conversations

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
```

## License

MIT
