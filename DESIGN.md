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
- Matrix credentials (stored globally at `~/.local/share/paca/.env` by default)
- Per-repo credentials (stored at `~/.local/share/paca/repos/<hash16>-<dirname>/.env`)
- Session file (`.paca_session` in per-repo share directory)
- Matrix store (`.nio_store` in per-repo share directory)

## Data Storage

### Global Storage
Credentials are stored in `~/.local/share/paca/.env` by default and shared across all repositories.

### Per-Repo Storage
Repository-specific files are stored in `~/.local/share/paca/repos/<hash16>-<dirname>/` where:
- `<hash16>`: First 16 characters of SHA256(absolute repo path)
- `<dirname>`: Directory name of the repo

### Storage Layout Example
```
~/.local/share/paca/
├── .env                    # Global Matrix credentials (default)
├── logs/
│   └── paca.log
└── repos/
    └── a3f2b8d1e4c5a7b9-my-app/   # Per-repo storage
        ├── .env            # Per-repo Matrix credentials (optional)
        ├── .paca_session   # Current session ID
        └── .nio_store/     # Matrix client store
```

### Credential Loading Priority
Environment variables and files are loaded in order (highest to lowest priority):
1. **Environment variables** (already set in shell)
2. **Local `.env`** in working directory (if exists)
3. **Per-repo `.env`** at `~/.local/share/paca/repos/<hash16>-<dirname>/.env`
4. **Global `.env`** at `~/.local/share/paca/.env`

### Login Commands
- `paca --login` - Saves credentials to global location (shared across repos)
- `paca --login --per-repo` - Saves credentials to per-repo location
