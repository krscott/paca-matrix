import base64
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from paca_matrix.__main__ import run_opencode_web


@pytest.fixture
def mock_webbrowser() -> Generator[MagicMock, None, None]:
    with patch("paca_matrix.__main__.webbrowser") as mock:
        yield mock


@pytest.fixture
def mock_get_share_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a temporary share directory for testing."""
    share_dir = tmp_path / "share"
    share_dir.mkdir(parents=True, exist_ok=True)

    with patch("paca_matrix.__main__.get_share_dir") as mock:
        mock.return_value = share_dir
        yield share_dir


@pytest.fixture
def mock_path_cwd() -> Generator[MagicMock, None, None]:
    """Mock Path.cwd() to return a predictable path."""
    with patch("paca_matrix.__main__.Path") as mock_path_class:
        mock_cwd = MagicMock()
        mock_cwd.resolve.return_value = "/home/user/project"
        mock_path_class.cwd.return_value = mock_cwd
        yield mock_path_class


def test_run_opencode_web_no_session(
    mock_webbrowser: MagicMock,
    mock_get_share_dir: Path,
    mock_path_cwd: MagicMock,
) -> None:
    """Test run_opencode_web without session ID."""
    run_opencode_web(4096, None)

    mock_webbrowser.open.assert_called_once_with("http://127.0.0.1:4096")


def test_run_opencode_web_with_explicit_session(
    mock_webbrowser: MagicMock,
    mock_get_share_dir: Path,
    mock_path_cwd: MagicMock,
) -> None:
    """Test run_opencode_web with explicit session ID."""
    session_id = "ses_test123"

    # Expected project ID
    # /home/user/project -> L2hvbWUvdXNlci9wcm9qZWN0 (base64)
    expected_project_id = (
        base64.urlsafe_b64encode(b"/home/user/project").decode().rstrip("=")
    )
    expected_url = f"http://127.0.0.1:4096/{expected_project_id}/session/{session_id}"

    run_opencode_web(4096, session_id)

    mock_webbrowser.open.assert_called_once_with(expected_url)


def test_run_opencode_web_with_stored_session(
    mock_webbrowser: MagicMock,
    mock_get_share_dir: Path,
    mock_path_cwd: MagicMock,
) -> None:
    """Test run_opencode_web with stored session ID from file."""
    session_id = "ses_stored"

    # Create the session file in the mock share directory
    session_file = mock_get_share_dir / ".paca_session"
    session_file.write_text(session_id)

    expected_project_id = (
        base64.urlsafe_b64encode(b"/home/user/project").decode().rstrip("=")
    )
    expected_url = f"http://127.0.0.1:4096/{expected_project_id}/session/{session_id}"

    run_opencode_web(4096, None)

    mock_webbrowser.open.assert_called_once_with(expected_url)
