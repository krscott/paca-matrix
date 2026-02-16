"""Shared utility functions for paca-matrix."""

import hashlib
import os
from pathlib import Path


def get_share_dir(cwd: Path | None = None) -> Path:
    """Get deterministic share directory for current repo.

    Creates a unique directory based on the repo's absolute path.
    Format: ~/.local/share/paca/repos/<hash16>-<dirname>/

    Args:
        cwd: Optional path to use instead of current working directory

    Returns:
        Path to the share directory (creates it if needed)
    """
    repo_path = (cwd or Path.cwd()).resolve()
    repo_hash = hashlib.sha256(str(repo_path).encode()).hexdigest()[:16]
    dir_name = repo_path.name or "unnamed"

    xdg_data_home = os.environ.get(
        "XDG_DATA_HOME", Path.home() / ".local" / "share"
    )
    share_dir = Path(xdg_data_home) / "paca" / "repos" / f"{repo_hash}-{dir_name}"
    share_dir.mkdir(parents=True, exist_ok=True)

    return share_dir
