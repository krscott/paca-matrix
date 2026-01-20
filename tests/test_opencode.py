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


def test_session_name_validation_invalid_characters():
    """Test that session names with invalid characters are rejected."""
    with pytest.raises(ValueError, match="Invalid session name format"):
        OpencodeClient("http://localhost:8080", "session/with/slashes")

    with pytest.raises(ValueError, match="Invalid session name format"):
        OpencodeClient("http://localhost:8080", "session with spaces")

    with pytest.raises(ValueError, match="Invalid session name format"):
        OpencodeClient("http://localhost:8080", "session$pecial")


def test_session_name_validation_too_long():
    """Test that session names exceeding max length are rejected."""
    from paca_matrix.opencode import MAX_SESSION_NAME_LENGTH

    long_name = "x" * (MAX_SESSION_NAME_LENGTH + 1)
    with pytest.raises(ValueError, match="Session name too long"):
        OpencodeClient("http://localhost:8080", long_name)


def test_session_name_validation_valid():
    """Test that valid session names are accepted."""
    # These should all work
    client = OpencodeClient("http://localhost:8080", "valid-session_123")
    assert client.session_name == "valid-session_123"

    client = OpencodeClient("http://localhost:8080", "UPPERCASE")
    assert client.session_name == "UPPERCASE"

    client = OpencodeClient("http://localhost:8080", "under_score")
    assert client.session_name == "under_score"


async def test_prompt_async_message_too_long():
    """Test that oversized messages are rejected."""
    from unittest.mock import AsyncMock, MagicMock

    from paca_matrix.opencode import MAX_MESSAGE_LENGTH

    client = OpencodeClient("http://localhost:8080")
    client.session_id = "test123"
    client.http_session = MagicMock()

    oversized = "x" * (MAX_MESSAGE_LENGTH + 1)
    with pytest.raises(ValueError, match="Message too long"):
        await client.prompt_async(oversized)


async def test_get_message_parts_invalid_message_id():
    """Test that invalid message IDs are rejected."""
    from unittest.mock import MagicMock

    client = OpencodeClient("http://localhost:8080")
    client.session_id = "test123"
    client.http_session = MagicMock()

    # Test path traversal attempt
    with pytest.raises(ValueError, match="Invalid message_id format"):
        await client.get_message_parts("../../../etc/passwd")

    # Test special characters
    with pytest.raises(ValueError, match="Invalid message_id format"):
        await client.get_message_parts("msg$pecial")

    # Test too long
    from paca_matrix.opencode import MAX_MESSAGE_ID_LENGTH

    long_id = "x" * (MAX_MESSAGE_ID_LENGTH + 1)
    with pytest.raises(ValueError, match="Invalid message_id length"):
        await client.get_message_parts(long_id)


async def test_reply_question_invalid_request_id():
    """Test that invalid request IDs are rejected."""
    from unittest.mock import MagicMock

    client = OpencodeClient("http://localhost:8080")
    client.http_session = MagicMock()

    # Test path traversal attempt
    with pytest.raises(ValueError, match="Invalid request_id format"):
        await client.reply_question("../../../etc/passwd", [["answer"]])

    # Test special characters
    with pytest.raises(ValueError, match="Invalid request_id format"):
        await client.reply_question("req$pecial", [["answer"]])

    # Test too long
    from paca_matrix.opencode import MAX_REQUEST_ID_LENGTH

    long_id = "x" * (MAX_REQUEST_ID_LENGTH + 1)
    with pytest.raises(ValueError, match="Invalid request_id length"):
        await client.reply_question(long_id, [["answer"]])
