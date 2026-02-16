"""Room authentication for paca-matrix."""

import logging
import random
import string
from pathlib import Path

log = logging.getLogger(__name__)


def generate_auth_code(length: int = 4) -> str:
    """Generate a random alphanumeric authentication code (case-insensitive).

    Args:
        length: Length of the code (default: 4)

    Returns:
        Uppercase alphanumeric code
    """
    return "".join(random.choices(string.ascii_uppercase, k=length))


def save_room_to_env(room_id: str, env_path: Path) -> None:
    """Save the authenticated room ID to the .env file.

    Args:
        room_id: The Matrix room ID to save
        env_path: Path to the .env file
    """
    env_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()

    # Remove existing PACAMATRIX_ROOM_ID line
    filtered_lines = [
        line for line in existing_lines if not line.startswith("PACAMATRIX_ROOM_ID=")
    ]

    # Add new room ID
    filtered_lines.append(f"PACAMATRIX_ROOM_ID={room_id}")

    # Write back
    env_path.write_text("\n".join(filtered_lines) + "\n")
    env_path.chmod(0o600)
    log.info("Saved room ID %s to %s", room_id, env_path)


def display_auth_code(code: str) -> None:
    """Display authentication code prominently.

    Args:
        code: The authentication code to display
    """
    log.info("Room authentication code: %s", code)

    border = "=" * (len(code) + 16)
    print()
    print(border)
    print(f"  AUTH CODE:  {code}  ")
    print(border)
    print("Send this code to the bot in any Matrix room to authenticate")
    print()
