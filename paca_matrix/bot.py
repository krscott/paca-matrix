import asyncio
import logging
import time
from typing import Any

from nio import Event, MatrixRoom, RoomMessageText

from paca_matrix.matrix import MatrixClient
from paca_matrix.opencode import OpencodeClient

log = logging.getLogger(__name__)


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
    ) -> None:
        self.matrix_bot = MatrixClient(
            homeserver=homeserver,
            user_id=user_id,
            device_id=device_id,
            access_token=access_token,
        )
        self.opencode_client = OpencodeClient(
            server_url=opencode_server_url, session_name=session_name
        )
        self.current_room: MatrixRoom | None = None
        self._event_listener_task: asyncio.Task[None] | None = None
        self._seen_event_ids: set[str] = set()
        self._start_time_ms: int = int(time.time() * 1000)

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

    async def _event_listener(self) -> None:
        """Background task that listens to OpenCode SSE events and forwards messages to Matrix."""
        message_parts: list[str] = []
        prev_event_type: str | None = None

        try:
            async for sse_event in self.opencode_client.subscribe_events():
                log.debug("SSE event: %s", sse_event.event)

                if sse_event.event == "message" and sse_event.data:
                    try:
                        data = sse_event.json()
                        await self._handle_opencode_event(
                            data, message_parts, prev_event_type
                        )
                        prev_event_type = data.get("type")
                    except Exception as e:
                        log.warning("Failed to parse SSE event data: %s", e)

        except asyncio.CancelledError:
            log.info("Event listener cancelled")
            raise

    async def _handle_opencode_event(
        self,
        data: dict[str, Any],
        message_parts: list[str],
        prev_event_type: str | None,
    ) -> None:
        """Process a single OpenCode event and send to Matrix if appropriate."""
        event_type = data.get("type")
        properties: dict[str, Any] = data.get("properties", {}) or {}

        # Handle message part events (text chunks from the agent)
        if event_type == "part.updated":
            part: dict[str, Any] = properties.get("part", {}) or {}
            if part.get("type") == "text":
                text = part.get("text", "")
                if isinstance(text, str) and text:
                    message_parts.append(text)

        # When a message completes, send accumulated text to Matrix
        elif event_type == "message.updated" and prev_event_type == "part.updated":
            if message_parts and self.current_room:
                full_message = "".join(message_parts)
                await self.send_to_matrix(self.current_room, full_message)
                message_parts.clear()

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
