from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.bot import PacaBot


@pytest.fixture
def mock_matrix_client():
    """Mock MatrixClient to avoid Matrix network calls."""
    with patch("paca_matrix.bot.MatrixClient", autospec=True) as mock:
        matrix_bot_instance = MagicMock()
        matrix_bot_instance.client = MagicMock()
        matrix_bot_instance.client.user = "@bot:example.com"
        matrix_bot_instance.send_message = AsyncMock()
        matrix_bot_instance.stop = AsyncMock()
        mock.return_value = matrix_bot_instance
        yield matrix_bot_instance


@pytest.fixture
def mock_opencode_client():
    """Mock OpencodeClient to avoid OpenCode network calls."""
    with patch("paca_matrix.bot.OpencodeClient", autospec=True) as mock:
        acp_instance = MagicMock()
        acp_instance.start = AsyncMock()
        acp_instance.stop = AsyncMock()
        mock.return_value = acp_instance
        yield acp_instance


def make_paca_bot() -> PacaBot:
    return PacaBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
        opencode_server_url="http://localhost:8080",
    )


async def test_send_to_matrix(mock_matrix_client, mock_opencode_client):
    """Test delegation to MatrixClient."""
    bot = make_paca_bot()

    room = MagicMock()
    await bot.send_to_matrix(room, "Hello, world!")

    mock_matrix_client.send_message.assert_called_once_with(room, "Hello, world!")


async def test_message_callback_from_self(mock_matrix_client, mock_opencode_client):
    """Test that bot ignores its own messages."""
    from nio import RoomMessageText

    bot = make_paca_bot()

    room = MagicMock()
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@bot:example.com"
    event.body = "Hello, myself!"

    await bot.message_callback(room, event)

    # Should not send any message
    mock_matrix_client.send_message.assert_not_called()


async def test_stop(mock_matrix_client, mock_opencode_client):
    """Test that stop() calls both components."""
    bot = make_paca_bot()

    await bot.stop()

    mock_opencode_client.stop.assert_called_once()
    mock_matrix_client.stop.assert_called_once()
