import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.matrix import MatrixBot


@pytest.fixture
def mock_async_client():
    with patch("paca_matrix.matrix.AsyncClient", autospec=True) as mock:
        client_instance = MagicMock()
        client_instance.access_token = None
        client_instance.user = "@bot:example.com"
        client_instance.room_send = AsyncMock()
        client_instance.sync = AsyncMock()
        client_instance.close = AsyncMock()
        client_instance.add_event_callback = MagicMock()
        client_instance.store = MagicMock()
        client_instance.next_batch = ""
        mock.return_value = client_instance
        yield mock, client_instance


def test_matrix_bot_initialization(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    assert bot.client == client_instance
    assert bot.client.access_token == "test_token"
    mock.assert_called_once_with(
        "https://example.com",
        "@bot:example.com",
        device_id="DEVICE123",
        store_path=".nio_store",
        config=mock.return_value.config,
    )


def test_matrix_bot_initialization_with_token(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="my_token",
    )

    assert bot.client.access_token == "my_token"


def test_matrix_bot_initialization_homeserver(mock_async_client):
    mock, client_instance = mock_async_client

    MatrixBot(
        homeserver="https://matrix.org",
        user_id="@bot:matrix.org",
        device_id="DEVICE123",
        access_token="token",
    )

    mock.assert_called_once()


async def test_send_message(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    room = MagicMock()
    room.room_id = "!room:example.com"

    await bot.send_message(room, "Hello, world!")

    client_instance.room_send.assert_called_once_with(
        room_id="!room:example.com",
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": "Hello, world!"},
    )


async def test_send_empty_message(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    room = MagicMock()
    room.room_id = "!room:example.com"

    await bot.send_message(room, "   ")  # Whitespace only

    # Should not send anything
    client_instance.room_send.assert_not_called()


async def test_setup_message_handler(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    callback = AsyncMock()
    await bot.setup_message_handler(callback)

    client_instance.add_event_callback.assert_called_once()
    # Check that the callback was passed to add_event_callback
    args = client_instance.add_event_callback.call_args[0]
    assert args[0] == callback


async def test_sync_forever(mock_async_client):
    mock, client_instance = mock_async_client

    # Mock SyncResponse
    from nio.responses import SyncResponse

    mock_sync_response = MagicMock(spec=SyncResponse)
    mock_sync_response.next_batch = "s123_456_789"

    call_count = 0

    async def stop_after_two_syncs(*args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_sync_response
        elif call_count >= 2:
            raise KeyboardInterrupt()

    client_instance.sync = AsyncMock(side_effect=stop_after_two_syncs)

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    with pytest.raises(KeyboardInterrupt):
        await bot.sync_forever()

    assert client_instance.sync.call_count >= 2


async def test_stop(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    await bot.stop()

    client_instance.close.assert_called_once()


async def test_sync_forever_cancelled_error(mock_async_client):
    mock, client_instance = mock_async_client

    async def raise_cancelled(*args):
        raise asyncio.CancelledError()

    client_instance.sync = AsyncMock(side_effect=raise_cancelled)

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    with pytest.raises(asyncio.CancelledError):
        await bot.sync_forever()


async def test_send_message_strips_whitespace(mock_async_client):
    mock, client_instance = mock_async_client

    bot = MatrixBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
    )

    room = MagicMock()
    room.room_id = "!room:example.com"

    await bot.send_message(room, "   Hello with spaces   ")

    client_instance.room_send.assert_called_once_with(
        room_id="!room:example.com",
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": "Hello with spaces"},
    )
