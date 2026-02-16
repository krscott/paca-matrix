"""Tests for room authentication module."""

import string
from pathlib import Path

from paca_matrix.room_auth import generate_auth_code, save_room_to_env


def test_generate_auth_code_default_length() -> None:
    """Test that auth code generation produces 4 character codes by default."""
    code = generate_auth_code()
    assert len(code) == 4
    assert all(c in string.ascii_uppercase for c in code)


def test_generate_auth_code_custom_length() -> None:
    """Test that auth code generation respects custom length."""
    code = generate_auth_code(length=6)
    assert len(code) == 6
    assert all(c in string.ascii_uppercase for c in code)


def test_generate_auth_code_uniqueness() -> None:
    """Test that generated codes are different (probabilistic test)."""
    codes = [generate_auth_code() for _ in range(100)]
    # With 26^4 = 456,976 possible codes, we should get mostly unique codes
    unique_codes = set(codes)
    assert len(unique_codes) > 90  # At least 90% unique


def test_save_room_to_env_creates_file(tmp_path: Path) -> None:
    """Test that saving room ID creates the .env file."""
    env_path = tmp_path / ".env"
    room_id = "!test:example.com"

    save_room_to_env(room_id, env_path)

    assert env_path.exists()
    content = env_path.read_text()
    assert f"PACAMATRIX_ROOM_ID={room_id}" in content


def test_save_room_to_env_creates_parent_dir(tmp_path: Path) -> None:
    """Test that saving room ID creates parent directories."""
    env_path = tmp_path / "nested" / "dir" / ".env"
    room_id = "!test:example.com"

    save_room_to_env(room_id, env_path)

    assert env_path.exists()
    assert env_path.parent.exists()


def test_save_room_to_env_preserves_other_vars(tmp_path: Path) -> None:
    """Test that saving room ID doesn't destroy other environment variables."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PACAMATRIX_HOMESERVER=https://matrix.example.com\n"
        "PACAMATRIX_USER_ID=@user:example.com\n"
        "PACAMATRIX_ACCESS_TOKEN=secret\n"
    )

    room_id = "!test:example.com"
    save_room_to_env(room_id, env_path)

    content = env_path.read_text()
    assert "PACAMATRIX_HOMESERVER=https://matrix.example.com" in content
    assert "PACAMATRIX_USER_ID=@user:example.com" in content
    assert "PACAMATRIX_ACCESS_TOKEN=secret" in content
    assert f"PACAMATRIX_ROOM_ID={room_id}" in content


def test_save_room_to_env_updates_existing_room_id(tmp_path: Path) -> None:
    """Test that saving room ID updates an existing room ID entry."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PACAMATRIX_HOMESERVER=https://matrix.example.com\n"
        "PACAMATRIX_ROOM_ID=!old:example.com\n"
        "PACAMATRIX_USER_ID=@user:example.com\n"
    )

    new_room_id = "!new:example.com"
    save_room_to_env(new_room_id, env_path)

    content = env_path.read_text()
    assert f"PACAMATRIX_ROOM_ID={new_room_id}" in content
    assert "PACAMATRIX_ROOM_ID=!old:example.com" not in content
    # Ensure we only have one PACAMATRIX_ROOM_ID line
    assert content.count("PACAMATRIX_ROOM_ID=") == 1


def test_save_room_to_env_sets_permissions(tmp_path: Path) -> None:
    """Test that .env file has correct permissions (600)."""
    env_path = tmp_path / ".env"
    room_id = "!test:example.com"

    save_room_to_env(room_id, env_path)

    # Check file permissions (owner read/write only)
    stat = env_path.stat()
    assert stat.st_mode & 0o777 == 0o600
