# paca-matrix

A Matrix echo bot implementation using matrix-nio.

## Features

- Echoes back messages received in Matrix rooms
- Async implementation using Python asyncio
- E2E encryption support via matrix-nio

## Installation

```bash
pip install -e '.[dev]'
```

Or using Nix:

```bash
nix develop
```

## Usage

### Command Line

```bash
paca --homeserver https://matrix.org --user-id @bot:example.com --access-token YOUR_TOKEN
```

### Environment Variables

Create a `.env` file or set environment variables:

```bash
export PACAMATRIX_HOMESERVER=https://matrix.org
export PACAMATRIX_USER_ID=@bot:example.com
export PACAMATRIX_ACCESS_TOKEN=YOUR_TOKEN
export PACAMATRIX_VERBOSE=1  # Optional: Enable debug logging
```

Then run:

```bash
paca
```

### Getting an Access Token

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
