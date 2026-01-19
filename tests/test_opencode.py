import pytest

from paca_matrix.opencode import OpencodeClient


def test_acp_client_initialization():
    """Test basic initialization sets attributes correctly."""
    client = OpencodeClient("http://localhost:8080", "test-session")
    assert client.server_url == "http://localhost:8080"
    assert client.session_name == "test-session"
    assert client.session_id is None
    assert client.http_session is None


def test_acp_client_initialization_without_session_name():
    """Test initialization without session name."""
    client = OpencodeClient("http://localhost:8080")
    assert client.server_url == "http://localhost:8080"
    assert client.session_name is None
    assert client.session_id is None
    assert client.http_session is None


async def test_acp_client_prompt_async_no_session():
    """Test that prompt_async raises error when session not initialized."""
    client = OpencodeClient("http://localhost:8080")
    # Don't set session_id or http_session

    with pytest.raises(RuntimeError, match="HTTP session not initialized"):
        await client.prompt_async("test message")


async def test_acp_client_subscribe_events_no_session():
    """Test that subscribe_events raises error when session not initialized."""
    client = OpencodeClient("http://localhost:8080")
    # Don't set http_session

    with pytest.raises(RuntimeError, match="HTTP session not initialized"):
        async for _ in client.subscribe_events():
            pass


async def test_acp_client_stop_no_session():
    """Test that stop() doesn't crash when no session exists."""
    client = OpencodeClient("http://localhost:8080")
    # Should not raise error
    await client.stop()
    assert client.http_session is None


async def test_acp_client_abort_session_no_session():
    """Test that abort_session raises error when session not initialized."""
    client = OpencodeClient("http://localhost:8080")
    # Don't set session_id or http_session

    with pytest.raises(RuntimeError, match="HTTP session not initialized"):
        await client.abort_session()
