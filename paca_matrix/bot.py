import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from nio import Event, MatrixRoom, RoomMessageText

from paca_matrix.matrix import MatrixClient
from paca_matrix.opencode import OpencodeClient

log = logging.getLogger(__name__)

# Maximum number of event/message IDs to track for deduplication
# This prevents unbounded memory growth in long-running bots
MAX_SEEN_EVENT_IDS = 10000
MAX_SENT_MESSAGE_IDS = 10000

# Input validation limits to prevent abuse and resource exhaustion
MAX_MESSAGE_LENGTH = 100_000  # 100KB max message size
MAX_QUESTION_OPTIONS = 100  # Maximum number of question options
MAX_QUESTION_RESPONSE_SELECTIONS = 50  # Maximum selections in multi-select


@dataclass
class QuestionOption:
    label: str
    description: str


@dataclass
class PendingQuestion:
    request_id: str
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
        # Use OrderedDict as LRU cache for seen event IDs (bounded memory)
        self._seen_event_ids: OrderedDict[str, None] = OrderedDict()
        self._start_time_ms: int = int(time.time() * 1000)
        # Use OrderedDict as LRU cache for sent message IDs (bounded memory)
        self._sent_message_ids: OrderedDict[str, None] = OrderedDict()
        self._pending_question: PendingQuestion | None = None
        self._should_exit: bool = False

    def _add_seen_event_id(self, event_id: str) -> None:
        """Add an event ID to the seen set with LRU eviction."""
        self._seen_event_ids[event_id] = None
        # Evict oldest entries if we exceed the max size
        while len(self._seen_event_ids) > MAX_SEEN_EVENT_IDS:
            self._seen_event_ids.popitem(last=False)

    def _add_sent_message_id(self, message_id: str) -> None:
        """Add a message ID to the sent set with LRU eviction."""
        self._sent_message_ids[message_id] = None
        # Evict oldest entries if we exceed the max size
        while len(self._sent_message_ids) > MAX_SENT_MESSAGE_IDS:
            self._sent_message_ids.popitem(last=False)

    def _validate_message_length(self, message: str, context: str = "message") -> bool:
        """Validate message length to prevent resource exhaustion.

        Returns True if valid, False if too long.
        """
        if len(message) > MAX_MESSAGE_LENGTH:
            log.warning(
                "%s exceeds maximum length: %d > %d",
                context,
                len(message),
                MAX_MESSAGE_LENGTH,
            )
            return False
        return True

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
            self._add_seen_event_id(event.event_id)

        log.info("Received from %s: %s", event.sender, event.body[:100])

        # Validate message length
        if not self._validate_message_length(event.body, "Matrix message"):
            log.warning("Rejecting oversized message from %s", event.sender)
            await self.matrix_bot.send_message(
                room,
                f"Message too long (max {MAX_MESSAGE_LENGTH:,} characters). "
                f"Your message was {len(event.body):,} characters.",
            )
            return

        # Mark message as read
        if event.event_id:
            await self.matrix_bot.read_receipt(room.room_id, event.event_id)

        # Track the current room for sending OpenCode responses
        self.current_room = room

        message_to_send = event.body
        # Check if this is a bang command
        if event.body.startswith("!"):
            command_handled, message_to_send = await self._handle_bang_command(
                event.body
            )
            if command_handled:
                return

        # Check if this is a response to a pending question
        if self._pending_question:
            response_handled = await self._handle_question_response(event.body)
            if response_handled:
                return

        try:
            if message_to_send is not None:
                await self.opencode_client.prompt_async(message_to_send)
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
                parts = response.split(",")
                # Prevent DoS via extremely long comma-separated lists
                if len(parts) > MAX_QUESTION_RESPONSE_SELECTIONS:
                    log.warning(
                        "Too many selections in question response: %d > %d",
                        len(parts),
                        MAX_QUESTION_RESPONSE_SELECTIONS,
                    )
                    if self.current_room:
                        await self.send_to_matrix(
                            self.current_room,
                            f"Too many selections (max {MAX_QUESTION_RESPONSE_SELECTIONS})",
                        )
                    return True
                indices = [int(x.strip()) for x in parts]
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

        # Convert indices to labels for sending to OpenCode
        labels = [self._pending_question.options[i].label for i in valid_indices]

        # Send answer via question reply endpoint
        try:
            await self.opencode_client.reply_question(
                request_id=self._pending_question.request_id,
                answers=[labels],
            )
            log.info(
                "Submitted question answer: %s (indices: %s)", labels, valid_indices
            )
            self._pending_question = None
            return True
        except Exception as e:
            log.exception("Failed to submit question answer: %s", e)
            if self.current_room:
                await self.send_to_matrix(
                    self.current_room, f"Error submitting answer: {e}"
                )
            return True

    async def _handle_bang_command(self, message: str) -> tuple[bool, str | None]:
        """Handle bang commands. Returns (handled, message_to_send)."""
        # Handle !! as escape to send to OpenCode
        if message.startswith("!!"):
            return False, message[1:]  # Strip one bang

        parts = message.strip().split(maxsplit=1)
        if not parts:
            return False, None

        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if command == "!echo":
            if len(args) == 0:
                if self.current_room:
                    await self.send_to_matrix(
                        self.current_room, "Usage: !echo <message>"
                    )
                return True, None
            echo_msg = args[0]
            if self.current_room:
                await self.send_to_matrix(self.current_room, f"Echo: {echo_msg}")
            return True, None

        if command == "!stop":
            try:
                await self.opencode_client.abort_session()
                if self.current_room:
                    await self.send_to_matrix(self.current_room, "Agent stopped.")
                return True, None
            except Exception as e:
                log.exception("Error stopping agent: %s", e)
                if self.current_room:
                    await self.send_to_matrix(
                        self.current_room, f"Error stopping agent: {e}"
                    )
                return True, None

        if command == "!kill":
            try:
                await self.opencode_client.abort_session()
                if self.current_room:
                    await self.send_to_matrix(
                        self.current_room, "Agent killed. Exiting..."
                    )
                self._should_exit = True
                return True, None
            except Exception as e:
                log.exception("Error killing agent: %s", e)
                if self.current_room:
                    await self.send_to_matrix(
                        self.current_room, f"Error killing agent: {e}"
                    )
                return True, None

        # Unknown command - send error
        if self.current_room:
            await self.send_to_matrix(
                self.current_room,
                f"Unrecognized command '{command}'. (To send to agent, send an extra bang '!! ...')",
            )
        return True, None

    async def _event_listener(self) -> None:
        """Background task that listens to OpenCode SSE events and forwards messages to Matrix."""
        try:
            async for sse_event in self.opencode_client.subscribe_events():
                log.debug(
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

    async def _exit_watcher(self, sync_task: asyncio.Task[None]) -> None:
        """Background task that checks if the bot should exit and stops sync."""
        while not self._should_exit:
            await asyncio.sleep(0.5)
        log.info("Exit flag set, stopping sync...")
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass

    async def _handle_question_event(self, properties: dict[str, Any]) -> None:
        """Handle question events from OpenCode and send to Matrix as numbered list."""
        request_id: str = properties.get("id", "")
        questions: list[dict[str, Any]] = properties.get("questions", [])

        if not questions:
            log.warning("Invalid question event: missing questions")
            return

        question_data: dict[str, Any] = questions[0]
        question: str = question_data.get("question", "")
        header: str = question_data.get("header", "")
        question_options: list[dict[str, Any]] = question_data.get("options", [])
        multiple: bool = question_data.get("multiple", False)

        if not question or not question_options:
            log.warning("Invalid question event: missing question or options")
            return

        # Validate question size to prevent resource exhaustion
        if len(question_options) > MAX_QUESTION_OPTIONS:
            log.warning(
                "Too many question options: %d > %d",
                len(question_options),
                MAX_QUESTION_OPTIONS,
            )
            if self.current_room:
                await self.send_to_matrix(
                    self.current_room,
                    f"Question has too many options ({len(question_options)}), "
                    f"maximum is {MAX_QUESTION_OPTIONS}. Please simplify the question.",
                )
            return

        log.info("Received question: %s", question[:100])

        # Parse options
        options = [
            QuestionOption(
                label=opt.get("label", ""), description=opt.get("description", "")
            )
            for opt in question_options
        ]

        # Store pending question
        self._pending_question = PendingQuestion(
            request_id=request_id,
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

        if event_type == "question.asked":
            await self._handle_question_event(properties)
            return

        elif event_type == "message.updated":
            # When a message is updated, fetch the full message and send to Matrix

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
                    self._add_sent_message_id(message_id)
                return

            if message_id and message_id not in self._sent_message_ids:
                try:
                    parts = await self.opencode_client.get_message_parts(message_id)
                    full_message = "".join(parts)

                    if full_message and self.current_room:
                        await self.send_to_matrix(self.current_room, full_message)
                        # Clear typing notification after sending message
                        await self.matrix_bot.set_typing(
                            self.current_room, typing=False
                        )
                    self._add_sent_message_id(message_id)
                except Exception as e:
                    log.exception(
                        "Failed to fetch and send message %s: %s", message_id, e
                    )

        else:
            # Send typing notification to indicate agent is working
            if self.current_room:
                await self.matrix_bot.set_typing(self.current_room, typing=True)

    async def run_forever(self) -> None:
        log.info("Starting bot...")
        await self.opencode_client.start()
        await self.matrix_bot.setup_message_handler(self.message_callback)

        # Start the event listener as a background task
        self._event_listener_task = asyncio.create_task(
            self._event_listener(), name="opencode_event_listener"
        )

        # Start the exit watcher task
        sync_task = asyncio.create_task(
            self.matrix_bot.sync_forever(), name="matrix_sync"
        )
        exit_watcher_task = asyncio.create_task(
            self._exit_watcher(sync_task), name="exit_watcher"
        )

        log.info("Bot started")

        try:
            await sync_task
        except asyncio.CancelledError:
            log.info("Sync cancelled")
        finally:
            # Ensure event listener is cancelled if sync exits
            if self._event_listener_task and not self._event_listener_task.done():
                self._event_listener_task.cancel()
                try:
                    await self._event_listener_task
                except asyncio.CancelledError:
                    pass

            if not exit_watcher_task.done():
                exit_watcher_task.cancel()
                try:
                    await exit_watcher_task
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
