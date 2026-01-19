import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from nio import Event, MatrixRoom, RoomMessageText

from paca_matrix.matrix import MatrixClient
from paca_matrix.opencode import OpencodeClient

log = logging.getLogger(__name__)


@dataclass
class QuestionOption:
    label: str
    description: str


@dataclass
class PendingQuestion:
    message_id: str
    question: str
    options: list[QuestionOption]
    multiple: bool


class PacaBot:
    def __init__(
        self,
        *,
        homeserver: str,
        user_id: str,
        device_id: str,
        access_token: str,
        opencode_server_url: str,
        session_name: str | None = None,
        model: str | None = None,
    ) -> None:
        self.matrix_bot = MatrixClient(
            homeserver=homeserver,
            user_id=user_id,
            device_id=device_id,
            access_token=access_token,
        )
        self.opencode_client = OpencodeClient(
            server_url=opencode_server_url,
            session_name=session_name,
            model=model,
        )
        self.current_room: MatrixRoom | None = None
        self._event_listener_task: asyncio.Task[None] | None = None
        self._seen_event_ids: set[str] = set()
        self._start_time_ms: int = int(time.time() * 1000)
        self._sent_message_ids: set[str] = set()
        self._pending_question: PendingQuestion | None = None

    async def send_to_matrix(self, room: MatrixRoom, message: str) -> None:
        await self.matrix_bot.send_message(room, message)

    async def message_callback(self, room: MatrixRoom, event: Event) -> None:
        """Handle incoming Matrix messages by forwarding them to OpenCode.

        Messages are sent asynchronously - responses arrive via the SSE event stream.
        """
        if not isinstance(event, RoomMessageText):
            return
        if event.sender == self.matrix_bot.client.user:
            return

        # Skip messages from before bot started (old sync history)
        server_ts = getattr(event, "server_timestamp", None)
        if server_ts and server_ts < self._start_time_ms:
            log.debug(
                "Skipping old message from %s: timestamp=%d < start=%d",
                event.sender,
                server_ts,
                self._start_time_ms,
            )
            return

        # Skip duplicate messages (from sync history)
        if event.event_id and event.event_id in self._seen_event_ids:
            log.debug("Skipping duplicate event: %s", event.event_id)
            return

        if event.event_id:
            self._seen_event_ids.add(event.event_id)

        log.info("Received from %s: %s", event.sender, event.body)

        # Track the current room for sending OpenCode responses
        self.current_room = room

        # Check if this is a response to a pending question
        if self._pending_question:
            response_handled = await self._handle_question_response(event.body)
            if response_handled:
                return

        try:
            await self.opencode_client.prompt_async(event.body)
        except Exception as e:
            log.exception("Error sending message to OpenCode: %s", e)
            await self.matrix_bot.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"Error sending to OpenCode: {e}",
                },
            )

    async def _handle_question_response(self, response: str) -> bool:
        """Handle a response to a pending question. Returns True if handled."""
        if not self._pending_question:
            return False

        response = response.strip()

        # Check if response is a number or comma-separated numbers
        try:
            if self._pending_question.multiple:
                indices = [int(x.strip()) for x in response.split(",")]
            else:
                indices = [int(response)]
        except ValueError:
            log.debug("Not a numeric response, treating as normal message")
            return False

        # Validate indices
        max_index = len(self._pending_question.options)
        valid_indices: list[int] = []
        for idx in indices:
            if 1 <= idx <= max_index:
                valid_indices.append(idx - 1)
            else:
                log.warning("Invalid question index: %d", idx)
                if self.current_room:
                    await self.send_to_matrix(
                        self.current_room,
                        f"Invalid selection: {idx}. Please choose 1-{max_index}",
                    )
                return True

        if not valid_indices:
            log.warning("No valid indices in response")
            if self.current_room:
                await self.send_to_matrix(
                    self.current_room, "Invalid selection. Please try again."
                )
            return True

        # Submit answer to OpenCode
        try:
            await self.opencode_client.answer_question(
                message_id=self._pending_question.message_id,
                indices=valid_indices,
            )
            log.info("Submitted question answer: %s", valid_indices)
            self._pending_question = None
            return True
        except Exception as e:
            log.exception("Failed to submit question answer: %s", e)
            if self.current_room:
                await self.send_to_matrix(
                    self.current_room, f"Error submitting answer: {e}"
                )
            return True

    async def _event_listener(self) -> None:
        """Background task that listens to OpenCode SSE events and forwards messages to Matrix."""
        try:
            async for sse_event in self.opencode_client.subscribe_events():
                log.info(
                    "SSE event: %s, data: %s",
                    sse_event.event,
                    sse_event.data if sse_event.data else None,
                )

                if sse_event.data:
                    try:
                        data = sse_event.json()
                        await self._handle_opencode_event(data)
                    except Exception as e:
                        log.exception("Failed to parse SSE event data: %s", e)

        except asyncio.CancelledError:
            log.info("Event listener cancelled")
            raise

    async def _handle_question_event(self, properties: dict[str, Any]) -> None:
        """Handle question events from OpenCode and send to Matrix as numbered list."""
        tool: dict[str, Any] = properties.get("tool", {}) or {}
        questions: list[dict[str, Any]] = properties.get("questions", [])

        if not questions or not tool:
            log.warning("Invalid question event: missing questions or tool info")
            return

        message_id: str = tool.get("messageID", "")
        question_data: dict[str, Any] = questions[0]
        question: str = question_data.get("question", "")
        header: str = question_data.get("header", "")
        question_options: list[dict[str, Any]] = question_data.get("options", [])
        multiple: bool = question_data.get("multiple", False)

        if not question or not question_options:
            log.warning("Invalid question event: missing question or options")
            return

        log.info("Received question: %s", question[:100])

        # Parse options
        options = [
            QuestionOption(label=opt.get("label", ""), description=opt.get("description", ""))
            for opt in question_options
        ]

        # Store pending question
        self._pending_question = PendingQuestion(
            message_id=message_id,
            question=question,
            options=options,
            multiple=multiple,
        )

        # Format question for Matrix
        lines: list[str] = []
        if header:
            lines.append(f"{header}")
            lines.append("")
        lines.append(f"Question: {question}")
        lines.append("")
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}. {opt.label}")
            if opt.description:
                lines.append(f"   {opt.description}")

        lines.append("")
        if multiple:
            lines.append("Reply with numbers separated by commas (e.g., 1,3)")
        else:
            lines.append("Reply with a number to select (e.g., 2)")

        message = "\n".join(lines)

        if self.current_room:
            await self.send_to_matrix(self.current_room, message)

    async def _handle_opencode_event(self, data: dict[str, Any]) -> None:
        """Process a single OpenCode event and send to Matrix if appropriate."""
        event_type = data.get("type")
        properties: dict[str, Any] = data.get("properties", {}) or {}

        # Handle question events
        if event_type == "question.asked":
            await self._handle_question_event(properties)
            return

        # When a message is updated, fetch the full message and send to Matrix
        if event_type == "message.updated":
            message_info: dict[str, Any] = properties.get("info", {}) or {}
            message_id: str | None = message_info.get("id")
            role = message_info.get("role", "")
            author = message_info.get("author", "")

            # Skip user messages to prevent echoing the user's input back to them
            if role == "user" or author == "user":
                log.debug(
                    "Skipping user message %s (role=%s, author=%s)",
                    message_id,
                    role,
                    author,
                )
                if message_id:
                    self._sent_message_ids.add(message_id)
                return

            if message_id and message_id not in self._sent_message_ids:
                try:
                    parts = await self.opencode_client.get_message_parts(message_id)
                    full_message = "".join(parts)

                    if full_message and self.current_room:
                        log.info("Sending message to Matrix: %s", full_message[:100])
                        await self.send_to_matrix(self.current_room, full_message)
                        self._sent_message_ids.add(message_id)
                except Exception as e:
                    log.exception(
                        "Failed to fetch and send message %s: %s", message_id, e
                    )

    async def run_forever(self) -> None:
        log.info("Starting bot...")
        await self.opencode_client.start()
        await self.matrix_bot.setup_message_handler(self.message_callback)

        # Start the event listener as a background task
        self._event_listener_task = asyncio.create_task(
            self._event_listener(), name="opencode_event_listener"
        )
        log.info("Bot started")

        try:
            await self.matrix_bot.sync_forever()
        finally:
            # Ensure event listener is cancelled if sync_forever exits
            if self._event_listener_task and not self._event_listener_task.done():
                self._event_listener_task.cancel()
                try:
                    await self._event_listener_task
                except asyncio.CancelledError:
                    pass

    async def stop(self) -> None:
        log.info("Stopping bot...")

        # Cancel the event listener task
        if self._event_listener_task and not self._event_listener_task.done():
            self._event_listener_task.cancel()
            try:
                await self._event_listener_task
            except asyncio.CancelledError:
                pass
            self._event_listener_task = None

        await self.opencode_client.stop()
        await self.matrix_bot.stop()
        log.info("Bot stopped")
