from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.opencode import ACPClient


@pytest.fixture
def mock_aiohttp_session():
    with patch("aiohttp.ClientSession", autospec=True) as mock_session_class:
        session_instance = MagicMock()
        # Mock context manager for post/get
        mock_post_context = MagicMock()
        mock_post_context.__aenter__ = AsyncMock()
        mock_post_context.__aexit__ = AsyncMock()
        session_instance.post.return_value = mock_post_context

        mock_get_context = MagicMock()
        mock_get_context.__aenter__ = AsyncMock()
        mock_get_context.__aexit__ = AsyncMock()
        session_instance.get.return_value = mock_get_context

        session_instance.close = AsyncMock()
        mock_session_class.return_value = session_instance
        yield mock_session_class, session_instance, mock_post_context, mock_get_context


def test_acp_client_initialization():
    client = ACPClient("http://localhost:8080", "test-session")
    assert client.server_url == "http://localhost:8080"
    assert client.session_name == "test-session"
    assert client.session_id is None
    assert client.http_session is None


def test_acp_client_initialization_without_session_name():
    client = ACPClient("http://localhost:8080")
    assert client.server_url == "http://localhost:8080"
    assert client.session_name is None
    assert client.session_id is None
    assert client.http_session is None


async def test_acp_client_start_new_session(mock_aiohttp_session):
    mock_session_class, session_instance, mock_post_context, mock_get_context = (
        mock_aiohttp_session
    )

    # Mock response for creating new session
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"id": "new-session-id"})
    mock_post_context.__aenter__.return_value = mock_response

    client = ACPClient("http://localhost:8080")
    await client.start()

    assert client.session_id == "new-session-id"
    assert client.http_session == session_instance
    session_instance.post.assert_called_once_with(
        "http://localhost:8080/session", json={}
    )


async def test_acp_client_start_existing_session(mock_aiohttp_session):
    mock_session_class, session_instance = mock_aiohttp_session

    # Mock response for connecting to existing session
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"id": "existing-session-id"})
    session_instance.get.return_value.__aenter__.return_value = mock_response

    client = ACPClient("http://localhost:8080", "existing-session")
    await client.start()

    assert client.session_id == "existing-session-id"
    assert client.http_session == session_instance
    session_instance.get.assert_called_once_with(
        "http://localhost:8080/session/existing-session"
    )


async def test_acp_client_start_existing_session_not_found(mock_aiohttp_session):
    mock_session_class, session_instance = mock_aiohttp_session

    # Mock response for failed connection
    mock_response = MagicMock()
    mock_response.status = 404
    mock_response.text = AsyncMock(return_value="Session not found")
    session_instance.get.return_value.__aenter__.return_value = mock_response

    client = ACPClient("http://localhost:8080", "nonexistent-session")

    with pytest.raises(
        RuntimeError, match="Failed to connect to session 'nonexistent-session'"
    ):
        await client.start()


async def test_acp_client_start_create_session_fails(mock_aiohttp_session):
    mock_session_class, session_instance = mock_aiohttp_session

    # Mock response for failed session creation
    mock_response = MagicMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Server error")
    session_instance.post.return_value.__aenter__.return_value = mock_response

    client = ACPClient("http://localhost:8080")

    with pytest.raises(RuntimeError, match="Failed to create session"):
        await client.start()


async def test_acp_client_prompt_stream(mock_aiohttp_session):
    mock_session_class, session_instance = mock_aiohttp_session

    # Setup client
    client = ACPClient("http://localhost:8080")
    client.session_id = "test-session"
    client.http_session = session_instance

    # Mock response for message
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={
            "parts": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": " world"},
            ]
        }
    )
    session_instance.post.return_value.__aenter__.return_value = mock_response

    updates = []
    async for update in client.prompt_stream("test message"):
        updates.append(update)

    assert len(updates) == 2
    assert updates[0]["update"]["sessionUpdate"] == "agent_message_chunk"
    assert updates[0]["update"]["content"]["text"] == "Hello"
    assert updates[1]["update"]["content"]["text"] == " world"

    session_instance.post.assert_called_once_with(
        "http://localhost:8080/session/test-session/message",
        json={"parts": [{"type": "text", "text": "test message"}]},
    )


async def test_acp_client_prompt_stream_no_session():
    client = ACPClient("http://localhost:8080")
    # Don't set session_id or http_session

    with pytest.raises(RuntimeError, match="HTTP session not initialized"):
        async for _ in client.prompt_stream("test message"):
            pass


async def test_acp_client_prompt_stream_http_error(mock_aiohttp_session):
    mock_session_class, session_instance = mock_aiohttp_session

    # Setup client
    client = ACPClient("http://localhost:8080")
    client.session_id = "test-session"
    client.http_session = session_instance

    # Mock error response
    mock_response = MagicMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Server error")
    session_instance.post.return_value.__aenter__.return_value = mock_response

    with pytest.raises(RuntimeError, match="HTTP error 500"):
        async for _ in client.prompt_stream("test message"):
            pass


async def test_acp_client_stop(mock_aiohttp_session):
    mock_session_class, session_instance = mock_aiohttp_session

    client = ACPClient("http://localhost:8080")
    client.http_session = session_instance

    await client.stop()

    assert client.http_session is None
    session_instance.close.assert_called_once()


async def test_acp_client_stop_no_session():
    client = ACPClient("http://localhost:8080")
    # Should not raise error
    await client.stop()
    assert client.http_session is None
