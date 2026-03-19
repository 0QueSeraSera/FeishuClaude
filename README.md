# FeishuClaude

Connect Feishu bot to local Claude Code CLI for interactive AI conversations.

## Features

- **Real-time chat**: Receive and respond to Feishu messages via WebSocket (long-connection)
- **Claude Code integration**: Use Claude Code CLI as the backend AI engine
- **Session management**: Maintain conversation context per chat
- **Command support**: Built-in commands for session management

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

3. **Run the bot**:
   ```bash
   feishu-claude
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
| `FEISHU_CONNECTION_MODE` | `long_connection` or `webhook` | No (default: long_connection) |
| `FEISHU_ALLOW_USER_IDS` | Comma-separated allowed user IDs | No (allow all) |
| `FEISHU_ALLOW_GROUP_CHATS` | Allow group chats | No (default: true) |
| `CLAUDE_WORKSPACE` | Working directory for Claude | No (default: current dir) |

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/new` | Start a new conversation session |
| `/sessions` | List all sessions |
| `/resume <id>` | Resume a previous session |
| `/status` | Show Claude Code status |

## Architecture

```
┌─────────────┐    WebSocket     ┌──────────────────┐
│  Feishu     │ ◄──────────────► │  FeishuAdapter   │
│  Server     │                  │  (lark-oapi)     │
└─────────────┘                  └────────┬─────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  ClaudeSession   │
                                 │  Manager         │
                                 └────────┬─────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  Claude Code CLI │
                                 │  (claude -p)     │
                                 └──────────────────┘
```

## How It Works

1. **Message Flow**:
   - Feishu user sends message to bot
   - FeishuAdapter receives via WebSocket
   - ClaudeSessionManager looks up or creates session
   - Message is sent to Claude Code CLI
   - Response is sent back to Feishu

2. **Session Management**:
   - Each Feishu chat has its own Claude Code session
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
