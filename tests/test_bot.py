from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.bot import EchoBot


@pytest.fixture
def mock_matrix_bot():
    with patch("paca_matrix.bot.MatrixBot", autospec=True) as mock:
        matrix_bot_instance = MagicMock()
        matrix_bot_instance.client = MagicMock()
        matrix_bot_instance.client.user = "@bot:example.com"
        matrix_bot_instance.client.room_send = AsyncMock()
        matrix_bot_instance.client.sync = AsyncMock()
        matrix_bot_instance.client.close = AsyncMock()
        matrix_bot_instance.client.add_event_callback = MagicMock()
        matrix_bot_instance.client.store = MagicMock()
        matrix_bot_instance.client.next_batch = ""
        matrix_bot_instance.send_message = AsyncMock()
        matrix_bot_instance.setup_message_handler = AsyncMock()
        matrix_bot_instance.sync_forever = AsyncMock()
        matrix_bot_instance.stop = AsyncMock()
        mock.return_value = matrix_bot_instance
        yield mock, matrix_bot_instance


@pytest.fixture
def mock_acp_client():
    with patch("paca_matrix.bot.ACPClient", autospec=True) as mock:
        acp_instance = MagicMock()
        acp_instance.start = AsyncMock()
        acp_instance.stop = AsyncMock()
        acp_instance.prompt_stream = AsyncMock()
        mock.return_value = acp_instance
        yield mock, acp_instance


@pytest.fixture
def bot(mock_matrix_bot, mock_acp_client):
    _mock_matrix, matrix_bot_instance = mock_matrix_bot
    _mock_acp, acp_instance = mock_acp_client
    return EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
    )


def test_bot_initialization(mock_matrix_bot, mock_acp_client):
    mock_matrix, matrix_bot_instance = mock_matrix_bot
    mock_acp, acp_instance = mock_acp_client

    bot = EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
    )

    assert bot.matrix_bot == matrix_bot_instance
    assert bot.acp_client == acp_instance
    mock_matrix.assert_called_once()
    mock_acp.assert_called_once()


def test_bot_initialization_with_session_name(mock_matrix_bot, mock_acp_client):
    mock_matrix, matrix_bot_instance = mock_matrix_bot
    mock_acp, acp_instance = mock_acp_client

    bot = EchoBot(
        "https://example.com",
        "@bot:example.com",
        "DEVICE123",
        "test_token",
        "http://localhost:8080",
        session_name="test-session",
    )

    mock_acp.assert_called_once_with(
        server_url="http://localhost:8080", session_name="test-session"
    )


async def test_send_to_matrix(bot, mock_matrix_bot):
    mock_matrix, matrix_bot_instance = mock_matrix_bot

    room = MagicMock()
    room.room_id = "!room:example.com"

    await bot.send_to_matrix(room, "Hello, world!")

    matrix_bot_instance.send_message.assert_called_once_with(room, "Hello, world!")


async def test_message_callback_from_other_user(bot):
    from nio import RoomMessageText

    room = MagicMock()
    room.room_id = "!room:example.com"
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Hello, bot!"

    async def mock_stream(*args):
        yield {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "AI response here"},
            }
        }

    bot.acp_client.prompt_stream = mock_stream

    await bot.message_callback(room, event)

    bot.matrix_bot.client.room_send.assert_called_once_with(
        room_id="!room:example.com",
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": "AI response here"},
    )


async def test_message_callback_from_self(bot):
    from nio import RoomMessageText

    room = MagicMock()
    room.room_id = "!room:example.com"
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@bot:example.com"
    event.body = "Hello, myself!"

    await bot.message_callback(room, event)
    bot.matrix_bot.client.room_send.assert_not_called()


async def test_message_callback_with_multiple_chunks(bot):
    from nio import RoomMessageText

    room = MagicMock()
    room.room_id = "!room:example.com"
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Hello, bot!"

    async def mock_stream(*args):
        yield {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Chunk 1"},
            }
        }
        yield {
            "update": {
                "sessionUpdate": "different_update",
                "content": {"type": "text", "text": "Should not be included"},
            }
        }
        yield {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Chunk 2"},
            }
        }

    bot.acp_client.prompt_stream = mock_stream

    await bot.message_callback(room, event)

    # Should have sent two messages: "Chunk 1" and "Chunk 2"
    assert bot.matrix_bot.client.room_send.call_count == 2

    # Check first call
    first_call = bot.matrix_bot.client.room_send.call_args_list[0]
    assert first_call[1]["content"]["body"] == "Chunk 1"

    # Check second call
    second_call = bot.matrix_bot.client.room_send.call_args_list[1]
    assert second_call[1]["content"]["body"] == "Chunk 2"


async def test_message_callback_error_handling(bot):
    from nio import RoomMessageText

    room = MagicMock()
    room.room_id = "!room:example.com"
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Hello, bot!"

    bot.acp_client.prompt_stream = AsyncMock(side_effect=Exception("Test error"))

    await bot.message_callback(room, event)

    # Should send error message
    bot.matrix_bot.client.room_send.assert_called_once()
    call_args = bot.matrix_bot.client.room_send.call_args[1]
    assert "Error processing message: Test error" in call_args["content"]["body"]


async def test_run_forever_sets_up_components(bot):
    await bot.run_forever()

    # Should start ACP client
    bot.acp_client.start.assert_called_once()

    # Should setup message handler
    bot.matrix_bot.setup_message_handler.assert_called_once()

    # Should start syncing
    bot.matrix_bot.sync_forever.assert_called_once()


async def test_stop(bot):
    await bot.stop()

    bot.acp_client.stop.assert_called_once()
    bot.matrix_bot.stop.assert_called_once()


async def test_run_forever_handles_keyboard_interrupt(bot):
    bot.matrix_bot.sync_forever = AsyncMock(side_effect=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        await bot.run_forever()

    # Should still start components
    bot.acp_client.start.assert_called_once()
    bot.matrix_bot.setup_message_handler.assert_called_once()
