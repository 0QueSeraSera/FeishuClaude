# FeishuClaude Memory

## Project Overview

FeishuClaude connects Feishu bot to local Claude Code CLI for interactive AI conversations.

## Architecture

```
Feishu Bot ──WebSocket──> FeishuAdapter ──> Bot ──> ClaudeRunner ──> Claude Code CLI
      ↑                                                              │
      └──────────────────── HTTP API <──────────────────────────────┘
```

## Key Components

- **config.py**: Settings management via pydantic-settings
- **feishu_adapter.py**: WebSocket connection to Feishu using lark-oapi
- **claude_runner.py**: Claude Code CLI invocation via subprocess
- **bot.py**: Main logic connecting Feishu to Claude
- **cli.py**: CLI entry point

## Reference Projects

1. **AtomAgent** (`~/workspace/OSS_contribute/AtomAgent-Workspace/AtomAgent`)
   - Full Feishu integration with lark-oapi
   - Message bus architecture
   - Session management patterns

2. **ralph-claude** (`~/bin/ralph-claude`)
   - Claude Code CLI invocation pattern
   - Uses `claude --print --dangerously-skip-permissions "$prompt"`

## Claude Code CLI Key Flags

- `-p` / `--print`: Non-interactive mode
- `-c` / `--continue`: Continue recent conversation
- `-r <session>` / `--resume`: Resume specific session
- `--output-format json`: JSON output
- `--dangerously-skip-permissions`: Skip permission prompts

## Feishu Configuration

Required environment variables:
- `FEISHU_APP_ID`: Feishu app ID
- `FEISHU_APP_SECRET`: Feishu app secret

Optional:
- `FEISHU_CONNECTION_MODE`: `long_connection` (default) or `webhook`
- `FEISHU_ALLOW_USER_IDS`: Comma-separated allowed user IDs
- `FEISHU_ALLOW_GROUP_CHATS`: `true`/`false`

## Running the Bot

```bash
# Install
pip install -e .

# Configure
cp .env.example .env
# Edit .env with credentials

# Run
feishu-claude

# Or with options
feishu-claude -v --workspace /path/to/project
```

## Bot Commands

| Command | Description |
|---------|-------------|
| `/help` | Show commands |
| `/new` | Start new session |
| `/sessions` | List sessions |
| `/status` | Bot status |
| `/ping` | Check responsiveness |
