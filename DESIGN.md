# Architecture Design

## Overview

Paca-matrix is a Matrix bot that bridges chat messages to OpenCode for remote AI-assisted coding. It connects to a Matrix homeserver, listens for messages, forwards them to an OpenCode HTTP API, and streams responses back to Matrix.

## Components

### PacaBot (`paca_matrix/bot.py`)
Core orchestrator that:
- Bridges Matrix and OpenCode communication
- Handles message deduplication (LRU cache, 10k entries max)
- Implements bang commands: `!help`, `!echo`, `!stop`, `!kill`, `!uptime`, `!new`, `!session`
- Processes OpenCode "questions" (user approval requests)
- Manages session lifecycle and auto-restart logic

### MatrixClient (`paca_matrix/matrix.py`)
Matrix protocol wrapper using `matrix-nio`:
- Handles SSL verification (relaxed for localhost)
- Sends messages, typing indicators, read receipts
- Syncs forever with callback-based message handling

### OpencodeClient (`paca_matrix/opencode.py`)
OpenCode HTTP API client:
- SSE event streaming with auto-reconnect
- Session management (create, switch, list)
- Message sending and retrieval
- Question handling for user approval flows
- Input validation for security

### CLI (`paca_matrix/__main__.py`)
Entry point with:
- Custom `EnvAction` for environment variable fallback
- Matrix login flow (`--login`)
- OpenCode server auto-start/management
- Signal handling for graceful shutdown
- Model validation against available OpenCode models

## Data Flow

```
User Message (Matrix)
        ↓
MatrixClient receives via sync
        ↓
PacaBot.on_message() callback
        ↓
Deduplication check (LRU cache)
        ↓
Bang command processing (if applicable)
        ↓
OpencodeClient.send_message()
        ↓
OpenCode HTTP API
        ↓
SSE event stream
        ↓
OpencodeClient receives response chunks
        ↓
PacaBot formats and sends via MatrixClient
        ↓
User sees response (Matrix)
```

## Security

- Input validation: Max lengths for messages, IDs, session names
- Path traversal protection: Alphanumeric validation for session names
- DoS prevention: Limits on question options and selections
- Credential file permissions: 0o600 for stored tokens
- SSL context handling: Verified for production, relaxed for localhost

## Reproducibility

To recreate this system:

1. **Dependencies**: Python 3.10+, Nix for reproducible environment
2. **Install**: `pip install -e '.[dev]'` or `nix develop`
3. **Matrix Setup**: `paca --login` to authenticate with homeserver
4. **OpenCode**: Either auto-start (default) or specify `--opencode-server-url`
5. **Run**: `paca` to start the bot

All state is ephemeral except:
- Matrix credentials (stored in `~/.local/share/paca/repos/<hash16>-<dirname>/.env`)
- Session file (`.paca_session` in share directory)
- Matrix store (`.nio_store` in share directory)

## Data Storage

Files are stored in `~/.local/share/paca/repos/<hash16>-<dirname>/` where:
- `<hash16>`: First 16 characters of SHA256(absolute repo path)
- `<dirname>`: Directory name of the repo

This provides a deterministic, unique location per repository that persists across working directory changes.

Example:
```
Repo: /home/user/projects/my-app
Share: ~/.local/share/paca/repos/a3f2b8d1e4c5a7b9-my-app/
  ├── .env              # Matrix credentials
  ├── .paca_session     # Current session ID
  └── .nio_store/       # Matrix client store
```

Environment files are loaded in order:
1. Local `.env` in working directory (if exists)
2. Share directory `.env` (overrides local values)
