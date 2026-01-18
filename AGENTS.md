# Agent Guide for py-start

Python project managed with **Nix**. Dev environment assumed active.

## Quick Reference

| Action | Command |
|--------|---------|
| Format code | `./format.sh` |
| Type check | `mypy .` |
| Run all tests | `pytest` |
| Run single test | `pytest tests/test_file.py::test_name` |

## 1. Environment & Dependencies

### Template

Run `./init-template.sh your_project_name` to initialize a new project from this template.
Then remove the example `greet` function and tests, and replace this "Template" section.

### Adding Dependencies

Three-layer system:
1. **`pyproject.toml`** - Source of truth for Python packages
2. **`default.nix`** - Maps to Nix packages (add to `propagatedBuildInputs`)
3. **`flake.nix`** - System-level dev tools only (add to `devPkgs`)

**Workflow:**
1. Add to `pyproject.toml` (`dependencies` or `optional-dependencies.dev`)
2. Add corresponding Nix package to `default.nix`
3. Run `pip install -e '.[dev]'`

**Important**: Always use `pip install -e '.[dev]'`, never `pip install <package>` directly.

## 2. Build, Test, and Lint

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

## 3. Code Style

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
* Absolute imports preferred: `from py_start.lib import greet`
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

## 4. Workflow

### Development Cycle
1. **Edit**: Make changes following style guidelines
2. **Verify**:
   * `./format.sh`
   * `mypy .` (zero errors)
   * `pytest` (write tests for new functionality)
3. **Commit**: Only after all checks pass

### Pre-Commit Checklist
- [ ] `./format.sh` run
- [ ] `mypy .` passes
- [ ] `pytest` passes
- [ ] New code has type hints and tests
- [ ] AGENTS.md updated if outdated

## 5. Reusable Components

### EnvAction

`EnvAction` in `py_start/__main__.py` provides argparse arguments with environment variable fallbacks:

```python
parser.add_argument(
    "-v", "--verbose",
    action=EnvAction,
    env_var="MYAPP_VERBOSE",
    nargs=0,
    help="show more detailed log messages",
)
```
