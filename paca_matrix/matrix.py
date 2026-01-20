import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable

from nio import (
    AsyncClient,
    AsyncClientConfig,
    Event,
    MatrixRoom,
    RoomMessageText,
    SyncResponse,
)

log = logging.getLogger(__name__)


class MatrixClient:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        device_id: str,
        access_token: str,
    ) -> None:
        config = AsyncClientConfig(store_sync_tokens=True)

        # Determine SSL verification setting
        # For production homeservers (HTTPS), enforce SSL verification
        # For local/dev servers (HTTP or localhost HTTPS), allow without verification
        ssl_verify: bool | ssl.SSLContext
        if homeserver.startswith("http://"):
            # Plain HTTP connection - no SSL verification needed
            ssl_verify = False
            log.info("Using HTTP connection (no SSL) to homeserver: %s", homeserver)
        elif "127.0.0.1" in homeserver or "localhost" in homeserver:
            # Localhost HTTPS - allow self-signed certificates for development
            log.warning(
                "SSL verification disabled for localhost homeserver: %s", homeserver
            )
            ssl_verify = False
        else:
            # Production homeserver - enforce full SSL verification
            ssl_verify = True
            log.info("SSL verification enabled for homeserver: %s", homeserver)

        self.client = AsyncClient(
            homeserver,
            user_id,
            device_id=device_id,
            store_path=".nio_store",
            config=config,
            ssl=ssl_verify,
        )
        self.client.access_token = access_token

    async def send_message(self, room: MatrixRoom, message: str) -> None:
        message = message.strip()
        if not message:
            log.warning("Skipping sending empty message")
            return

        log.debug("Sending to %s: %s", room.room_id, message)

        await self.client.room_send(
            room_id=room.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message},
        )

    async def read_receipt(self, room_id: str, event_id: str) -> None:
        await self.client.room_read_markers(
            room_id=room_id, fully_read_event=event_id, read_event=event_id
        )

    async def set_typing(self, room: MatrixRoom, typing: bool = True) -> None:
        """Set or clear typing notification for a room."""
        timeout = 5000 if typing else 0
        await self.client.room_typing(
            room_id=room.room_id,
            typing_state=typing,
            timeout=timeout,
        )

    async def setup_message_handler(
        self, callback: Callable[[MatrixRoom, Event], Awaitable[None]]
    ) -> None:
        self.client.add_event_callback(
            callback,
            RoomMessageText,
        )

    async def sync_forever(self) -> None:
        response = await self.client.sync()
        if isinstance(response, SyncResponse):
            log.info(
                "Initial sync complete, next_batch: %s",
                response.next_batch[:20] + "...",
            )

        try:
            while True:
                await self.client.sync()
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise

    async def stop(self) -> None:
        log.info("Stopping Matrix client...")
        await self.client.close()
        log.info("Matrix client stopped")
