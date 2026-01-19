# paca-matrix

A Matrix bot that connects Matrix rooms to OpenCode for AI-powered responses.

## Features

- Forwards Matrix messages to OpenCode and streams responses back
- Async implementation using Python asyncio
- E2E encryption support via matrix-nio
- Supports both subprocess (`opencode acp`) and HTTP (`opencode serve`) modes

## Installation

```bash
pip install -e '.[dev]'
```

Or using Nix:

```bash
nix develop
```

## Usage

### Initial Setup (Login)

To set up credentials for the first time, use the `--login` flag:

```bash
paca --login
```

You will be prompted for:
- Homeserver URL (e.g., `https://matrix.org`)
- Username
- Password
- Device name (optional, defaults to `paca-bot`)

Credentials will be saved to a `.env` file with restricted permissions (0o600).

### Command Line

Once credentials are configured, run the bot:

```bash
paca
```

Or specify credentials manually:

```bash
paca --homeserver https://matrix.org --user-id @bot:example.com --access-token YOUR_TOKEN
```

### Environment Variables

Create a `.env` file or set environment variables:

```bash
PACAMATRIX_HOMESERVER=https://matrix.org
PACAMATRIX_USER_ID=@bot:example.com
PACAMATRIX_ACCESS_TOKEN=YOUR_TOKEN
PACAMATRIX_DEVICE_ID=YOUR_DEVICE_ID
PACAMATRIX_VERBOSE=1  # Optional: Enable debug logging
PACAMATRIX_OPENCODE_SERVER_URL=http://127.0.0.1:8765  # Optional: Connect to opencode serve
```

Then run:

```bash
paca
```

### OpenCode Server Modes

The bot can connect to OpenCode in two ways:

**1. Subprocess mode (default)**
```bash
paca
```
Automatically starts `opencode acp` as a subprocess. This is the default behavior.

**2. HTTP serve mode**
```bash
# In one terminal, start opencode serve
opencode serve --port 8765

# In another terminal, run the bot with server URL
paca --opencode-server-url http://127.0.0.1:8765

# Or using environment variable
PACAMATRIX_OPENCODE_SERVER_URL=http://127.0.0.1:8765 paca
```
Connects to an existing `opencode serve` instance. This is useful for:
- Debugging the bot separately from the OpenCode server
- Running multiple clients against the same server
- Using a remote OpenCode server

### Getting Credentials

There are two ways to set up credentials:

**Option 1: Use `--login` flag (recommended)**
```bash
paca --login
```
This automatically logs you in and saves credentials to `.env`.

**Option 2: Manual setup**
1. Create a Matrix account for your bot
2. Use the Element web client or similar to get an access token
3. In Element, open Settings → Help & About → Advanced → Access Token
4. Copy the token and use it in the bot configuration

## Development

```bash
# Format code
./format.sh

# Type check
mypy .

# Run tests
pytest

# Run single test
pytest tests/test_bot.py::test_bot_initialization
```

## Documentation

- **README.md** - User-facing project documentation (this file)
- [**AGENTS.md**](AGENTS.md) - Comprehensive development guidelines for AI agents
  (Note: CLAUDE.md is symlinked to AGENTS.md in nix dev shell)
