from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.bot import EchoBot


@pytest.fixture
def mock_async_client():
    with patch("paca_matrix.bot.AsyncClient", autospec=True) as mock:
        client_instance = MagicMock()
        client_instance.access_token = None
        client_instance.user = "@bot:example.com"
        client_instance.room_send = AsyncMock()
        client_instance.sync = AsyncMock()
        client_instance.close = AsyncMock()
        client_instance.add_event_callback = MagicMock()
        mock.return_value = client_instance
        yield mock, client_instance


@pytest.fixture
def bot(mock_async_client):
    _mock, client_instance = mock_async_client
    return EchoBot("https://example.com", "@bot:example.com", "test_token")


def test_bot_initialization(mock_async_client):
    mock, client_instance = mock_async_client
    bot = EchoBot("https://example.com", "@bot:example.com", "test_token")
    assert bot.client == client_instance
    assert bot.client.access_token == "test_token"


async def test_bot_start(bot):
    await bot.start()
    bot.client.add_event_callback.assert_not_called()
    bot.client.sync.assert_not_called()


async def test_bot_run_forever_does_initial_sync(bot):
    call_count = 0

    async def stop_after_two_syncs(*args):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            await bot.stop()
            raise SystemExit()

    bot.client.sync = AsyncMock(side_effect=stop_after_two_syncs)

    try:
        await bot.run_forever()
    except SystemExit:
        pass

    assert bot.client.sync.call_count >= 2
    bot.client.add_event_callback.assert_called_once()


async def test_bot_stop(bot):
    await bot.stop()
    bot.client.close.assert_called_once()


async def test_message_callback_from_other_user(bot):
    room = MagicMock()
    room.room_id = "!room:example.com"
    event = MagicMock()
    event.sender = "@user:example.com"
    event.body = "Hello, bot!"

    await bot.message_callback(room, event)
    bot.client.room_send.assert_called_once_with(
        room_id="!room:example.com",
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": "Hello, bot!"},
    )


async def test_message_callback_from_self(bot):
    room = MagicMock()
    room.room_id = "!room:example.com"
    event = MagicMock()
    event.sender = "@bot:example.com"
    event.body = "Hello, myself!"

    await bot.message_callback(room, event)
    bot.client.room_send.assert_not_called()


def test_bot_initialization_with_token(mock_async_client):
    mock, client_instance = mock_async_client
    bot = EchoBot("https://example.com", "@bot:example.com", "my_token")
    assert bot.client.access_token == "my_token"


def test_bot_initialization_homeserver(mock_async_client):
    mock, client_instance = mock_async_client
    EchoBot("https://matrix.org", "@bot:matrix.org", "token")
    mock.assert_called_once_with("https://matrix.org", "@bot:matrix.org")
