# paca-matrix

A Matrix bot that connects to OpenCode for remote vibe coding.

## Security and Privacy

This bot wraps an OpenCode isntance and as such is intended to only run in
a **containerized** environment and connect to **trusted** chatrooms.

This bot does not support Matrix end-to-end encryption.

This bot is ~90% vibe-coded with itself. Caveat emptor.

## Features

- Forwards Matrix messages to OpenCode and streams responses back
- Sets up a local OpenCode server that can be separately attached to

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
paca --opencode-server-url http://127.0.0.1:8765
```

Or specify credentials manually:

```bash
paca --homeserver https://matrix.org --user-id @bot:example.com --device-id YOUR_DEVICE_ID --access-token YOUR_TOKEN --opencode-server-url http://127.0.0.1:8765
```

**Available options:**
- `--homeserver` - Matrix homeserver URL
- `--user-id` - Matrix user ID
- `--device-id` - Matrix device ID
- `--access-token` - Matrix access token
- `--opencode-server-url` - OpenCode server URL (required)
- `--session` - Session ID to connect to (optional)
- `--model` - OpenCode model ID (optional)
- `--verbose` - Enable debug logging
- `--login` - Set up Matrix credentials interactively

### Environment Variables

Create a `.env` file or set environment variables:

```bash
PACAMATRIX_HOMESERVER=https://matrix.org
PACAMATRIX_USER_ID=@bot:example.com
PACAMATRIX_ACCESS_TOKEN=YOUR_TOKEN
PACAMATRIX_DEVICE_ID=YOUR_DEVICE_ID
PACAMATRIX_OPENCODE_SERVER_URL=http://127.0.0.1:8765
PACAMATRIX_SESSION=SESSION_ID  # Optional: Session ID to connect to
PACAMATRIX_MODEL=anthropic/claude-3-5-sonnet-20241022  # Optional: OpenCode model ID
PACAMATRIX_VERBOSE=1  # Optional: Enable debug logging
```

Then run:

```bash
paca
```

### OpenCode Server Modes

The bot connects to OpenCode via HTTP. You must specify `--opencode-server-url`:

```bash
# In one terminal, start opencode serve
opencode serve --port 8765

# In another terminal, run the bot
paca --opencode-server-url http://127.0.0.1:8765

# Or using environment variable
PACAMATRIX_OPENCODE_SERVER_URL=http://127.0.0.1:8765 paca
```

### Additional Options

**Session Management**
```bash
paca --session SESSION_ID  # Connect to existing session
```
If not specified, a new session will be created.

**Model Selection**
```bash
paca --model anthropic/claude-3-5-sonnet-20241022
```
Specify the OpenCode model to use. If not specified, the default model will be used.

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
# Type check
mypy .

# Run tests
pytest

# Run single test
pytest tests/test_bot.py::test_bot_initialization

# Format code
./format.sh
```

## Documentation

- **README.md** - User-facing project documentation (this file)
- [**AGENTS.md**](AGENTS.md) - Comprehensive development guidelines for AI agents
  (Note: CLAUDE.md is symlinked to AGENTS.md in nix dev shell)
