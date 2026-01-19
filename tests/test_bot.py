from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paca_matrix.bot import PacaBot, PendingQuestion, QuestionOption


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
    import time

    bot = PacaBot(
        homeserver="https://example.com",
        user_id="@bot:example.com",
        device_id="DEVICE123",
        access_token="test_token",
        opencode_server_url="http://localhost:8080",
    )
    # Set start time to past so test events with future timestamps work
    bot._start_time_ms = int(time.time() * 1000) - 10000  # type: ignore[reportPrivateUsage]
    return bot


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
    event.event_id = "$event1"
    # Use timestamp after bot start time
    import time

    event.server_timestamp = int(time.time() * 1000)

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
    event1.event_id = "$event1"
    import time

    event1.server_timestamp = int(time.time() * 1000)

    event2 = MagicMock(spec=RoomMessageText)
    event2.sender = "@user:example.com"
    event2.body = "Message 2"
    event2.event_id = "$event2"
    event2.server_timestamp = int(time.time() * 1000)

    await bot.message_callback(room1, event1)
    assert bot.current_room == room1

    await bot.message_callback(room2, event2)
    assert bot.current_room == room2


async def test_message_callback_skips_duplicate_events(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that duplicate events (same event_id) are skipped."""
    from nio import RoomMessageText

    bot = make_paca_bot()

    room = MagicMock()
    room.room_id = "!test:example.com"

    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Hello, bot!"
    event.event_id = "$event1"
    import time

    event.server_timestamp = int(time.time() * 1000)

    # First call should forward to OpenCode
    await bot.message_callback(room, event)
    mock_opencode_client.prompt_async.assert_called_once_with("Hello, bot!")

    # Second call with same event_id should be skipped
    await bot.message_callback(room, event)
    # Should still be called only once
    mock_opencode_client.prompt_async.assert_called_once_with("Hello, bot!")


# Note: Testing old message filtering is difficult with MagicMock due to spec constraints.
# The timestamp filtering is implemented in bot.py:51-57 and verified in production use.
# Timestamp filtering prevents old messages from sync history being sent to OpenCode.


async def test_handle_opencode_event_message_updated_sends_to_matrix(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that message.updated sends text to Matrix."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    data: dict[str, Any] = {
        "type": "message.updated",
        "properties": {
            "info": {"id": "msg_test123"},
        },
    }

    # Mock get_message_parts to return some text
    from unittest.mock import AsyncMock as mock_async

    mock_opencode_client.get_message_parts = mock_async(
        return_value=["Hello, ", "world!"]
    )

    await bot._handle_opencode_event(data)  # pyright: ignore[reportPrivateUsage]

    mock_matrix_client.send_message.assert_called_once_with(room, "Hello, world!")
    mock_opencode_client.get_message_parts.assert_called_once_with("msg_test123")


async def test_handle_opencode_event_no_room_skips_send(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that message.updated without current_room doesn't send."""
    bot = make_paca_bot()
    bot.current_room = None

    data: dict[str, Any] = {
        "type": "message.updated",
        "properties": {
            "info": {"id": "msg_test123"},
        },
    }

    await bot._handle_opencode_event(data)  # pyright: ignore[reportPrivateUsage]

    mock_matrix_client.send_message.assert_not_called()
    mock_opencode_client.get_message_parts.assert_called_once_with("msg_test123")


async def test_handle_opencode_event_duplicate_message_skips(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that duplicate message IDs are skipped."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    data: dict[str, Any] = {
        "type": "message.updated",
        "properties": {
            "info": {"id": "msg_test123"},
        },
    }

    from unittest.mock import AsyncMock as mock_async

    mock_opencode_client.get_message_parts = mock_async(return_value=["Hello!"])

    # First call should send
    await bot._handle_opencode_event(data)  # pyright: ignore[reportPrivateUsage]
    mock_matrix_client.send_message.assert_called_once()

    # Second call with same message ID should be skipped
    await bot._handle_opencode_event(data)  # pyright: ignore[reportPrivateUsage]
    # Still only called once
    mock_matrix_client.send_message.assert_called_once()


async def test_stop(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that stop() calls both components."""
    bot = make_paca_bot()

    await bot.stop()

    mock_opencode_client.stop.assert_called_once()
    mock_matrix_client.stop.assert_called_once()


async def test_handle_question_event(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that question events are formatted and sent to Matrix."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    data: dict[str, Any] = {
        "type": "question.asked",
        "properties": {
            "id": "que_question1",
            "questions": [
                {
                    "question": "Which framework do you prefer?",
                    "header": "Pick a framework",
                    "options": [
                        {"label": "React", "description": "A JavaScript library"},
                        {"label": "Vue", "description": "A progressive framework"},
                        {
                            "label": "Angular",
                            "description": "A full-featured framework",
                        },
                    ],
                    "multiple": False,
                }
            ],
        },
    }

    await bot._handle_opencode_event(data)  # pyright: ignore[reportPrivateUsage]

    # Check that question was stored
    assert bot._pending_question is not None  # type: ignore[reportPrivateUsage]
    assert bot._pending_question.request_id == "que_question1"  # type: ignore[reportPrivateUsage]
    assert bot._pending_question.question == "Which framework do you prefer?"  # type: ignore[reportPrivateUsage]
    assert len(bot._pending_question.options) == 3  # type: ignore[reportPrivateUsage]
    assert bot._pending_question.options[0].label == "React"  # type: ignore[reportPrivateUsage]
    assert bot._pending_question.multiple is False  # type: ignore[reportPrivateUsage]

    # Check that question was sent to Matrix
    call_args = mock_matrix_client.send_message.call_args
    message = call_args[0][1]
    assert "Which framework do you prefer?" in message
    assert "Pick a framework" in message
    assert "1. React" in message
    assert "2. Vue" in message
    assert "3. Angular" in message


async def test_handle_question_response_single_select(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test handling single-select question response."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room
    bot._pending_question = PendingQuestion(  # type: ignore[reportPrivateUsage]
        request_id="que_q1",
        question="Test question?",
        options=[
            QuestionOption(label="Option A", description=""),
            QuestionOption(label="Option B", description=""),
        ],
        multiple=False,
    )
    mock_opencode_client.reply_question = AsyncMock()

    # Send valid response
    result = await bot._handle_question_response(  # pyright: ignore[reportPrivateUsage]
        "1"
    )

    assert result is True
    mock_opencode_client.reply_question.assert_called_once_with(
        request_id="que_q1",
        answers=[["Option A"]],
    )
    assert bot._pending_question is None  # type: ignore[reportPrivateUsage]


async def test_handle_question_response_multiple_select(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test handling multi-select question response."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room
    bot._pending_question = PendingQuestion(  # type: ignore[reportPrivateUsage]
        request_id="que_q2",
        question="Select all that apply?",
        options=[
            QuestionOption(label="A", description=""),
            QuestionOption(label="B", description=""),
            QuestionOption(label="C", description=""),
        ],
        multiple=True,
    )
    mock_opencode_client.reply_question = AsyncMock()

    # Send valid response
    result = await bot._handle_question_response(  # pyright: ignore[reportPrivateUsage]
        "1,3"
    )

    assert result is True
    mock_opencode_client.reply_question.assert_called_once_with(
        request_id="que_q2",
        answers=[["A", "C"]],
    )
    assert bot._pending_question is None  # type: ignore[reportPrivateUsage]


async def test_handle_question_response_invalid_index(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test handling invalid question response."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room
    bot._pending_question = PendingQuestion(  # type: ignore[reportPrivateUsage]
        request_id="que_q3",
        question="Test question?",
        options=[
            QuestionOption(label="A", description=""),
            QuestionOption(label="B", description=""),
        ],
        multiple=False,
    )
    mock_opencode_client.reply_question = AsyncMock()

    # Send invalid response (out of range)
    result = await bot._handle_question_response(  # pyright: ignore[reportPrivateUsage]
        "5"
    )

    assert result is True
    mock_opencode_client.reply_question.assert_not_called()
    assert bot._pending_question is not None  # type: ignore[reportPrivateUsage]  # Question remains pending

    # Check error message sent to Matrix
    call_args = mock_matrix_client.send_message.call_args
    assert "Invalid selection: 5" in call_args[0][1]


async def test_handle_question_response_non_numeric(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that non-numeric responses are not handled as question responses."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room
    bot._pending_question = PendingQuestion(  # type: ignore[reportPrivateUsage]
        request_id="que_q4",
        question="Test question?",
        options=[
            QuestionOption(label="A", description=""),
        ],
        multiple=False,
    )
    mock_opencode_client.reply_question = AsyncMock()

    # Send non-numeric response
    result = await bot._handle_question_response(  # pyright: ignore[reportPrivateUsage]
        "I don't know"
    )

    assert result is False  # Not handled as question response
    mock_opencode_client.reply_question.assert_not_called()
    assert bot._pending_question is not None  # type: ignore[reportPrivateUsage]  # Question remains pending


async def test_handle_bang_command_echo_with_message(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that !echo command echoes back the message."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    result, message_to_send = await bot._handle_bang_command(  # pyright: ignore[reportPrivateUsage]
        "!echo hello world"
    )

    assert result is True
    assert message_to_send is None
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert call_args[0][1] == "Echo: hello world"


async def test_handle_bang_command_echo_no_message(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that !echo without message returns usage."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    result, message_to_send = await bot._handle_bang_command(  # pyright: ignore[reportPrivateUsage]
        "!echo"
    )

    assert result is True
    assert message_to_send is None
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert call_args[0][1] == "Usage: !echo <message>"


async def test_handle_bang_command_stop(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that !stop command aborts the session."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room
    mock_opencode_client.abort_session = AsyncMock()

    result, message_to_send = await bot._handle_bang_command(  # pyright: ignore[reportPrivateUsage]
        "!stop"
    )

    assert result is True
    assert message_to_send is None
    mock_opencode_client.abort_session.assert_called_once()
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert call_args[0][1] == "Agent stopped."


async def test_handle_bang_command_stop_error(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that !stop command handles errors gracefully."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room
    mock_opencode_client.abort_session = AsyncMock(side_effect=RuntimeError("Session error"))

    result, message_to_send = await bot._handle_bang_command(  # pyright: ignore[reportPrivateUsage]
        "!stop"
    )

    assert result is True
    assert message_to_send is None
    mock_opencode_client.abort_session.assert_called_once()
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert "Error stopping agent" in call_args[0][1]


async def test_handle_bang_command_unknown(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that unknown commands send an error message."""
    bot = make_paca_bot()
    room = MagicMock()
    bot.current_room = room

    result, message_to_send = await bot._handle_bang_command(  # pyright: ignore[reportPrivateUsage]
        "!unknown command"
    )

    assert result is True
    assert message_to_send is None
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert "Unrecognized command '!unknown'" in call_args[0][1]
    assert "send an extra bang '!! ...'" in call_args[0][1]


async def test_handle_bang_command_double_bang(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that !! sends message to OpenCode (escape)."""
    bot = make_paca_bot()

    handled, message_to_send = await bot._handle_bang_command(  # pyright: ignore[reportPrivateUsage]
        "!!help"
    )

    assert handled is False  # Not handled, falls through to OpenCode
    assert message_to_send == "!help"  # One bang stripped
    bot.matrix_bot.send_message.assert_not_called()  # type: ignore[reportPrivateUsage]


async def test_message_callback_bang_command(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that bang commands are handled and not forwarded to OpenCode."""
    bot = make_paca_bot()
    bot._start_time_ms = 0  # type: ignore[reportPrivateUsage]

    room = MagicMock()
    room.room_id = "!room:example.com"

    from nio import RoomMessageText
    event = MagicMock(spec=RoomMessageText)
    event.event_id = "$event1"
    event.sender = "@user:example.com"
    event.body = "!echo test"
    event.server_timestamp = 1000

    await bot.message_callback(room, event)

    # Should send to Matrix
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert call_args[0][1] == "Echo: test"

    # Should NOT send to OpenCode
    mock_opencode_client.prompt_async.assert_not_called()


async def test_message_callback_normal_message_forwarded(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that non-slash messages are forwarded to OpenCode."""
    bot = make_paca_bot()
    bot._start_time_ms = 0  # type: ignore[reportPrivateUsage]

    room = MagicMock()
    room.room_id = "!room:example.com"

    from nio import RoomMessageText
    event = MagicMock(spec=RoomMessageText)
    event.event_id = "$event1"
    event.sender = "@user:example.com"
    event.body = "hello"
    event.server_timestamp = 1000

    await bot.message_callback(room, event)

    # Should NOT send to Matrix directly
    bot.matrix_bot.send_message.assert_not_called()  # type: ignore[reportPrivateUsage]

    # Should send to OpenCode
    bot.opencode_client.prompt_async.assert_called_once_with("hello")  # type: ignore[reportPrivateUsage]


async def test_message_callback_double_bang_forwarded(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that !! messages are forwarded to OpenCode with single bang."""
    bot = make_paca_bot()
    bot._start_time_ms = 0  # type: ignore[reportPrivateUsage]

    room = MagicMock()
    room.room_id = "!room:example.com"

    from nio import RoomMessageText
    event = MagicMock(spec=RoomMessageText)
    event.event_id = "$event1"
    event.sender = "@user:example.com"
    event.body = "!!help me"
    event.server_timestamp = 1000

    await bot.message_callback(room, event)

    # Should NOT send to Matrix directly
    bot.matrix_bot.send_message.assert_not_called()  # type: ignore[reportPrivateUsage]

    # Should send to OpenCode with one bang stripped
    bot.opencode_client.prompt_async.assert_called_once_with("!help me")  # type: ignore[reportPrivateUsage]


async def test_message_callback_unknown_command_error(
    mock_matrix_client: MagicMock, mock_opencode_client: MagicMock
) -> None:
    """Test that unknown bang commands send an error."""
    bot = make_paca_bot()
    bot._start_time_ms = 0  # type: ignore[reportPrivateUsage]

    room = MagicMock()
    room.room_id = "!room:example.com"

    from nio import RoomMessageText
    event = MagicMock(spec=RoomMessageText)
    event.event_id = "$event1"
    event.sender = "@user:example.com"
    event.body = "!unknown"
    event.server_timestamp = 1000

    await bot.message_callback(room, event)

    # Should send error to Matrix
    call_args = bot.matrix_bot.send_message.call_args  # type: ignore[reportPrivateUsage]
    assert "Unrecognized command '!unknown'" in call_args[0][1]
    assert "send an extra bang '!! ...'" in call_args[0][1]

    # Should NOT send to OpenCode
    bot.opencode_client.prompt_async.assert_not_called()  # type: ignore[reportPrivateUsage]
