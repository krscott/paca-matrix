import pytest

from paca_matrix.opencode import ACPClient


def test_acp_client_initialization():
    """Test basic initialization sets attributes correctly."""
    client = ACPClient("http://localhost:8080", "test-session")
    assert client.server_url == "http://localhost:8080"
    assert client.session_name == "test-session"
    assert client.session_id is None
    assert client.http_session is None


def test_acp_client_initialization_without_session_name():
    """Test initialization without session name."""
    client = ACPClient("http://localhost:8080")
    assert client.server_url == "http://localhost:8080"
    assert client.session_name is None
    assert client.session_id is None
    assert client.http_session is None


async def test_acp_client_prompt_stream_no_session():
    """Test that prompt_stream raises error when session not initialized."""
    client = ACPClient("http://localhost:8080")
    # Don't set session_id or http_session

    with pytest.raises(RuntimeError, match="HTTP session not initialized"):
        async for _ in client.prompt_stream("test message"):
            pass


async def test_acp_client_stop_no_session():
    """Test that stop() doesn't crash when no session exists."""
    client = ACPClient("http://localhost:8080")
    # Should not raise error
    await client.stop()
    assert client.http_session is None
