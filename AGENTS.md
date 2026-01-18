# Agent Guide for paca-matrix

Python project managed with **Nix**. Dev environment assumed active.

## Quick Reference

| Action | Command |
|--------|---------|
| Login to Matrix | `paca --login` |
| Format code | `./format.sh` |
| Type check | `mypy .` |
| Run all tests | `pytest` |
| Run single test | `pytest tests/test_file.py::test_name` |
| Check Nix flake | `nix flake show '.?submodules=1'` |

## 1. Project Overview

This is a Matrix echo bot using the matrix-nio library. The bot connects to a Matrix homeserver and echoes back messages it receives in rooms.

### Project Structure

- `paca_matrix/bot.py` - EchoBot class implementing Matrix message handling
- `paca_matrix/__main__.py` - CLI entry point with argparse and EnvAction
- `tests/test_bot.py` - Bot unit tests using pytest and pytest-asyncio
- `tests/test_env_action.py` - Tests for EnvAction argument parser

## 2. Environment & Dependencies

### Adding Dependencies

Three-layer system:
1. **`pyproject.toml`** - Source of truth for Python packages
2. **`default.nix`** - Maps to Nix packages (add to `propagatedBuildInputs`)
3. **`flake.nix`** - Dev tools (add to `pythonDev` for Python packages)

**Workflow:**
1. Add to `pyproject.toml` (`dependencies` or `optional-dependencies.dev`)
2. Add corresponding Nix package to `default.nix`
3. For dev dependencies, also add to `pythonDev` in `flake.nix`
4. Run `pip install -e '.[dev]'` (No need to reload nix develop shell)

## 3. Build, Test, and Lint

### Formatting
* **Command**: `./format.sh` (runs isort, black, nix fmt)
* **Rule**: ALWAYS run before committing

### Type Checking
* **Command**: `mypy .`
* **Rule**: Zero errors allowed. All code must have type hints.
* Config in `pyproject.toml` under `[tool.mypy]`

### Testing
* Tests in `tests/` directory
* Use pytest fixtures for setup/teardown

## 4. Code Style

### Type Hints
Use modern Python 3.10+ syntax:

```python
# BAD
def log_messages(messages: List[Optional[str]]):
    ...

# GOOD
def log_messages(messages: list[str | None]) -> None:
    ...
```

Avoid `Any` and `# type: ignore` unless necessary.

### Imports
* Absolute imports preferred: `from paca_matrix.bot import EchoBot`
* isort handles organization automatically

### Error Handling
Prefer returning values over throwing exceptions.

```python
# Prefer values when error is handled locally
def process_data(data: dict[str, str]) -> int | None:
    try:
        return int(data["key"])
    except (KeyError, ValueError):
        return None

# Use exceptions when caller needs to handle or for crash-with-trace
def process_data(data: dict[str, str]) -> int:
    try:
        return int(data["key"])
    except KeyError as e:
        log.error("Missing required key: %s", e)
        raise
```

### Logging
* `print()` for direct user output (CLI responses)
* `logging` module for operational messages
* Use `log = logging.getLogger(__name__)`

### File System
Use `pathlib.Path` instead of `os.path`.

## 5. Workflow

### Development Cycle
1. **Edit**: Make changes following style guidelines
2. **Verify**:
   * `./format.sh`
   * `mypy .` (zero errors)
   * `pytest` (write tests for new functionality)
   * `nix flake show '.?submodules=1'` (no nix errors)
3. **Commit**: Only after all checks pass

### Pre-Commit Checklist
- [ ] `./format.sh` run
- [ ] `mypy .` passes
- [ ] `pytest` passes
- [ ] `nix flake show '.?submodules=1'` succeeds
- [ ] New code has type hints and tests
- [ ] AGENTS.md and README.md updated if outdated

## 6. Reusable Components

### EnvAction

`EnvAction` in `paca_matrix/__main__.py` provides argparse arguments with environment variable fallbacks:

```python
parser.add_argument(
    "--homeserver",
    action=EnvAction,
    env_var="PACAMATRIX_HOMESERVER",
    help="Matrix homeserver URL (env: PACAMATRIX_HOMESERVER)",
)
```
