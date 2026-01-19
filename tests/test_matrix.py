from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.matrix import MatrixClient


@pytest.fixture
def mock_async_client():
    """Mock nio AsyncClient to avoid network calls."""
    with patch("paca_matrix.matrix.AsyncClient", autospec=True) as mock:
        client_instance = MagicMock()
        client_instance.access_token = None
        client_instance.room_send = AsyncMock()
        client_instance.close = AsyncMock()
        mock.return_value = client_instance
        yield client_instance


def test_matrix_bot_initialization(mock_async_client):
    """Test basic initialization."""
    bot = MatrixClient(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    assert bot.client == mock_async_client
    assert bot.client.access_token == "test_token"


async def test_send_message(mock_async_client):
    """Test sending a message calls the Matrix client."""
    bot = MatrixClient(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    room = MagicMock()
    room.room_id = "!room:example.com"

    await bot.send_message(room, "Hello, world!")

    mock_async_client.room_send.assert_called_once_with(
        room_id="!room:example.com",
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": "Hello, world!"},
    )


async def test_send_empty_message(mock_async_client):
    """Test that empty messages are not sent."""
    bot = MatrixClient(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    room = MagicMock()
    room.room_id = "!room:example.com"

    await bot.send_message(room, "   ")  # Whitespace only

    # Should not send anything
    mock_async_client.room_send.assert_not_called()


async def test_stop(mock_async_client):
    """Test that stop() closes the client."""
    bot = MatrixClient(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    await bot.stop()

    mock_async_client.close.assert_called_once()
