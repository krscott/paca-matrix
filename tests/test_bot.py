from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.bot import EchoBot


@pytest.fixture
def mock_matrix_bot():
    """Mock MatrixBot to avoid Matrix network calls."""
    with patch("paca_matrix.bot.MatrixBot", autospec=True) as mock:
        matrix_bot_instance = MagicMock()
        matrix_bot_instance.client = MagicMock()
        matrix_bot_instance.client.user = "@bot:example.com"
        matrix_bot_instance.send_message = AsyncMock()
        matrix_bot_instance.stop = AsyncMock()
        mock.return_value = matrix_bot_instance
        yield matrix_bot_instance


@pytest.fixture
def mock_acp_client():
    """Mock ACPClient to avoid OpenCode network calls."""
    with patch("paca_matrix.bot.ACPClient", autospec=True) as mock:
        acp_instance = MagicMock()
        acp_instance.start = AsyncMock()
        acp_instance.stop = AsyncMock()
        mock.return_value = acp_instance
        yield acp_instance


def test_bot_initialization(mock_matrix_bot, mock_acp_client):
    """Test that EchoBot creates both components."""
    bot = EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
    )

    assert bot.matrix_bot == mock_matrix_bot
    assert bot.acp_client == mock_acp_client


async def test_send_to_matrix(mock_matrix_bot, mock_acp_client):
    """Test delegation to MatrixBot."""
    bot = EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
    )

    room = MagicMock()
    await bot.send_to_matrix(room, "Hello, world!")

    mock_matrix_bot.send_message.assert_called_once_with(room, "Hello, world!")


async def test_message_callback_from_self(mock_matrix_bot, mock_acp_client):
    """Test that bot ignores its own messages."""
    from nio import RoomMessageText

    bot = EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
    )

    room = MagicMock()
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@bot:example.com"
    event.body = "Hello, myself!"

    await bot.message_callback(room, event)

    # Should not send any message
    mock_matrix_bot.send_message.assert_not_called()


async def test_stop(mock_matrix_bot, mock_acp_client):
    """Test that stop() calls both components."""
    bot = EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
    )

    await bot.stop()

    mock_acp_client.stop.assert_called_once()
    mock_matrix_bot.stop.assert_called_once()
