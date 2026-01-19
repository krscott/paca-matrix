from typing import Any
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
        opencode_instance = MagicMock()
        opencode_instance.start = AsyncMock()
        opencode_instance.stop = AsyncMock()
        opencode_instance.prompt_async = AsyncMock()
        mock.return_value = opencode_instance
        yield opencode_instance


def make_paca_bot() -> PacaBot:
    return PacaBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
        opencode_server_url="http://localhost:8080",
    )


async def test_send_to_matrix(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test delegation to MatrixClient."""
    bot = make_paca_bot()

    room = MagicMock()
    await bot.send_to_matrix(room, "Hello, world!")

    mock_matrix_client.send_message.assert_called_once_with(room, "Hello, world!")


async def test_message_callback_from_self(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that bot ignores its own messages."""
    from nio import RoomMessageText

    bot = make_paca_bot()

    room = MagicMock()
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@bot:example.com"
    event.body = "Hello, myself!"

    await bot.message_callback(room, event)

    # Should not send any message to OpenCode
    mock_opencode_client.prompt_async.assert_not_called()


async def test_message_callback_forwards_to_opencode(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that messages from other users are forwarded to OpenCode."""
    from nio import RoomMessageText

    bot = make_paca_bot()

    room = MagicMock()
    room.room_id = "!test:example.com"
    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Hello, bot!"

    await bot.message_callback(room, event)

    # Should forward message to OpenCode via prompt_async
    mock_opencode_client.prompt_async.assert_called_once_with("Hello, bot!")
    # Should track the current room
    assert bot.current_room == room


async def test_message_callback_updates_current_room(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that current_room is updated on each message."""
    from nio import RoomMessageText

    bot = make_paca_bot()

    room1 = MagicMock()
    room1.room_id = "!room1:example.com"
    room2 = MagicMock()
    room2.room_id = "!room2:example.com"

    event1 = MagicMock(spec=RoomMessageText)
    event1.sender = "@user:example.com"
    event1.body = "Message 1"

    event2 = MagicMock(spec=RoomMessageText)
    event2.sender = "@user:example.com"
    event2.body = "Message 2"

    await bot.message_callback(room1, event1)
    assert bot.current_room == room1

    await bot.message_callback(room2, event2)
    assert bot.current_room == room2


async def test_handle_opencode_event_part_updated(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that part.updated events accumulate text."""
    bot = make_paca_bot()
    message_parts: list[str] = []

    data: dict[str, Any] = {
        "type": "part.updated",
        "properties": {
            "part": {
                "type": "text",
                "text": "Hello, ",
            }
        },
    }

    await bot._handle_opencode_event(
        data, message_parts, None
    )  # pyright: ignore[reportPrivateUsage]

    assert message_parts == ["Hello, "]


async def test_handle_opencode_event_message_updated_sends_to_matrix(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that message.updated after part.updated sends accumulated text to Matrix."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    message_parts = ["Hello, ", "world!"]

    data: dict[str, Any] = {
        "type": "message.updated",
        "properties": {},
    }

    await bot._handle_opencode_event(
        data, message_parts, "part.updated"
    )  # pyright: ignore[reportPrivateUsage]

    mock_matrix_client.send_message.assert_called_once_with(room, "Hello, world!")
    assert message_parts == []  # Should be cleared


async def test_handle_opencode_event_no_room_skips_send(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that message.updated without current_room doesn't send."""
    bot = make_paca_bot()
    bot.current_room = None

    message_parts = ["Hello!"]

    data: dict[str, Any] = {
        "type": "message.updated",
        "properties": {},
    }

    await bot._handle_opencode_event(
        data, message_parts, "part.updated"
    )  # pyright: ignore[reportPrivateUsage]

    mock_matrix_client.send_message.assert_not_called()
    # Parts should still be there since we couldn't send
    assert message_parts == ["Hello!"]


async def test_stop(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that stop() calls both components."""
    bot = make_paca_bot()

    await bot.stop()

    mock_opencode_client.stop.assert_called_once()
    mock_matrix_client.stop.assert_called_once()
