"""Tests for the get_share_dir helper function."""

import hashlib
from pathlib import Path

import pytest

from paca_matrix.utils import get_share_dir


class TestGetShareDir:
    """Tests for the get_share_dir function."""

    def test_default_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that get_share_dir uses current working directory by default."""
        # Set up a temporary home directory for XDG_DATA_HOME
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)
        monkeypatch.setenv("XDG_DATA_HOME", str(home_dir / ".local" / "share"))

        # Change to a directory we control
        test_cwd = tmp_path / "my-repo"
        test_cwd.mkdir()
        monkeypatch.chdir(test_cwd)

        # Calculate expected path
        repo_hash = hashlib.sha256(str(test_cwd.resolve()).encode()).hexdigest()[:16]
        expected_dir = (
            home_dir / ".local" / "share" / "paca" / "repos" / f"{repo_hash}-my-repo"
        )

        result = get_share_dir()

        assert result == expected_dir
        assert result.exists()

    def test_custom_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that get_share_dir accepts a custom cwd parameter."""
        # Set up a temporary home directory for XDG_DATA_HOME
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)
        monkeypatch.setenv("XDG_DATA_HOME", str(home_dir / ".local" / "share"))

        # Create a custom directory
        custom_dir = tmp_path / "custom-project"
        custom_dir.mkdir()

        # Calculate expected path
        repo_hash = hashlib.sha256(str(custom_dir.resolve()).encode()).hexdigest()[:16]
        expected_dir = (
            home_dir / ".local" / "share" / "paca" / "repos" / f"{repo_hash}-custom-project"
        )

        result = get_share_dir(cwd=custom_dir)

        assert result == expected_dir
        assert result.exists()

    def test_hash_uniqueness(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that different paths produce different hashes."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)
        monkeypatch.setenv("XDG_DATA_HOME", str(home_dir / ".local" / "share"))

        # Create two different directories with the same name
        parent = tmp_path / "parent"
        parent.mkdir()
        dir1 = parent / "project"
        dir1.mkdir()
        dir2 = parent / "subdir" / "project"
        dir2.mkdir(parents=True)

        result1 = get_share_dir(cwd=dir1)
        result2 = get_share_dir(cwd=dir2)

        assert result1 != result2
        assert result1.name != result2.name or result1.parent != result2.parent

    def test_xdg_data_home_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that XDG_DATA_HOME environment variable is respected."""
        custom_xdg = tmp_path / "custom-xdg"
        custom_xdg.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(custom_xdg))

        test_cwd = tmp_path / "test-repo"
        test_cwd.mkdir()
        monkeypatch.chdir(test_cwd)

        repo_hash = hashlib.sha256(str(test_cwd.resolve()).encode()).hexdigest()[:16]
        expected_dir = custom_xdg / "paca" / "repos" / f"{repo_hash}-test-repo"

        result = get_share_dir()

        assert result == expected_dir

    def test_directory_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that the directory is created if it doesn't exist."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)
        monkeypatch.setenv("XDG_DATA_HOME", str(home_dir / ".local" / "share"))

        test_cwd = tmp_path / "new-repo"
        test_cwd.mkdir()
        monkeypatch.chdir(test_cwd)

        repo_hash = hashlib.sha256(str(test_cwd.resolve()).encode()).hexdigest()[:16]
        expected_dir = (
            home_dir / ".local" / "share" / "paca" / "repos" / f"{repo_hash}-new-repo"
        )

        # Ensure directory doesn't exist before calling
        assert not expected_dir.exists()

        result = get_share_dir()

        assert result.exists()
        assert result.is_dir()

    def test_empty_dirname_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty dirnames fallback to 'unnamed'."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)
        monkeypatch.setenv("XDG_DATA_HOME", str(home_dir / ".local" / "share"))

        # Create a path that resolves to root (edge case)
        root_path = Path("/")

        repo_hash = hashlib.sha256(str(root_path.resolve()).encode()).hexdigest()[:16]
        expected_dir = home_dir / ".local" / "share" / "paca" / "repos" / f"{repo_hash}-unnamed"

        result = get_share_dir(cwd=root_path)

        # Should contain 'unnamed' in the path
        assert "unnamed" in result.name or result == expected_dir
