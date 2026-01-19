import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
from nio import (
    AsyncClient,
    AsyncClientConfig,
    Event,
    MatrixRoom,
    RoomMessageText,
    SyncResponse,
)

log = logging.getLogger(__name__)


class ACPClient:
    """Client for communicating with OpenCode via HTTP"""

    def __init__(
        self,
        server_url: str,
        session_name: str | None = None,
    ) -> None:
        self.session_id: str | None = None
        self.server_url = server_url
        self.session_name = session_name
        self.http_session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        await self._start_http()

    async def _start_http(self) -> None:
        log.info("Connecting to OpenCode server at %s...", self.server_url)
        self.http_session = aiohttp.ClientSession()

        if self.session_name:
            # Connect to existing session
            log.debug("Connecting to session: %s", self.session_name)
            async with self.http_session.get(
                f"{self.server_url}/session/{self.session_name}"
            ) as resp:
                if resp.status == 200:
                    session_data = await resp.json()
                    self.session_id = session_data["id"]
                    log.info("Connected to existing session: %s", self.session_id)
                    return
                else:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Failed to connect to session '{self.session_name}': {resp.status} {text}"
                    )

        # Create a new session (let OpenCode assign the ID)
        log.debug("Creating new session...")
        async with self.http_session.post(
            f"{self.server_url}/session", json={}
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Failed to create session: {resp.status} {text}")
            session_data = await resp.json()
            self.session_id = session_data["id"]
            log.info("Created session: %s", self.session_id)

    async def prompt_stream(self, message: str) -> AsyncIterator[dict[str, Any]]:
        async for update in self._prompt_stream_http(message):
            yield update

    async def _prompt_stream_http(self, message: str) -> AsyncIterator[dict[str, Any]]:
        if not self.session_id or not self.http_session or not self.server_url:
            raise RuntimeError("HTTP session not initialized")

        # Send message using synchronous endpoint
        message_url = f"{self.server_url}/session/{self.session_id}/message"
        log.debug("Sending message to: %s", message_url)

        async with self.http_session.post(
            message_url,
            json={
                "parts": [{"type": "text", "text": message}],
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP error {resp.status}: {text}")

            response_data = await resp.json()

            # Extract text from response parts
            parts = response_data.get("parts", [])
            for part in parts:
                if part.get("type") == "text":
                    text_content = part.get("text", "")
                    if text_content:
                        # Yield in the expected format for compatibility with existing code
                        yield {
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {
                                    "type": "text",
                                    "text": text_content,
                                },
                            },
                        }

    async def stop(self) -> None:
        if self.http_session:
            await self.http_session.close()
            self.http_session = None
            log.info("Closed OpenCode HTTP session")


class EchoBot:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        device_id: str,
        access_token: str,
        opencode_server_url: str,
        session_name: str | None = None,
    ) -> None:
        config = AsyncClientConfig(store_sync_tokens=True)

        self.client = AsyncClient(
            homeserver,
            user_id,
            device_id=device_id,
            store_path=".nio_store",
            config=config,
        )
        self.client.access_token = access_token
        self.acp_client = ACPClient(
            server_url=opencode_server_url, session_name=session_name
        )

    async def send_to_matrix(self, room: MatrixRoom, message: str) -> None:
        message = message.strip()
        if not message:
            log.info("Skipping empty message")
            return

        log.info("Sending to %s: %s", room.room_id, message)

        await self.client.room_send(
            room_id=room.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message},
        )

    async def message_callback(self, room: MatrixRoom, event: Event) -> None:
        if not isinstance(event, RoomMessageText):
            return
        if event.sender == self.client.user:
            return

        log.info("Received from %s: %s", event.sender, event.body)

        message_parts: list[str] = []
        prev_update_type = ""

        try:
            async for update in self.acp_client.prompt_stream(event.body):
                log.debug("opencode: %s", update)
                update_type = update.get("update", {}).get("sessionUpdate")

                if update_type == "agent_message_chunk":
                    content = update.get("update", {}).get("content", {})
                    if content.get("type") == "text":
                        text = content.get("text", "")
                        assert isinstance(text, str)
                        message_parts.append(text)

                if (
                    update_type != prev_update_type
                    and prev_update_type == "agent_message_chunk"
                ):
                    await self.send_to_matrix(room, "".join(message_parts))
                    message_parts.clear()

                prev_update_type = update_type

            await self.send_to_matrix(room, "".join(message_parts))

        except Exception as e:
            log.exception("Error processing message: %s", e)
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"Error processing message: {e}"},
            )

    async def run_forever(self) -> None:
        log.info("Starting bot...")
        await self.acp_client.start()
        log.info("Bot started")

        response = await self.client.sync()
        if isinstance(response, SyncResponse):
            log.info(
                "Initial sync complete, next_batch: %s",
                response.next_batch[:20] + "...",
            )

        self.client.add_event_callback(
            self.message_callback,
            RoomMessageText,
        )

        try:
            while True:
                await self.client.sync()
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise

    async def stop(self) -> None:
        log.info("Stopping bot...")
        await self.acp_client.stop()
        await self.client.close()
        log.info("Bot stopped")
