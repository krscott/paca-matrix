import asyncio
import logging

from nio import MatrixRoom  # type: ignore
from nio import AsyncClient, AsyncClientConfig, RoomMessageText, SyncResponse

log = logging.getLogger(__name__)

OPENCODE_MODEL = "opencode/glm-4.7-free"


class EchoBot:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        device_id: str,
        access_token: str,
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

    async def message_callback(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == self.client.user:
            return

        log.debug("Received message from %s: %s", event.sender, event.body)

        try:
            proc = await asyncio.create_subprocess_exec(
                "opencode",
                "-m",
                OPENCODE_MODEL,
                "run",
                event.body,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() or "Unknown error"
                log.error("Opencode command failed: %s", error_msg)
                response = f"Error: {error_msg}"
            else:
                response = stdout.decode().strip()

            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": response},
            )

            log.debug("Sent response back to %s", room.room_id)
        except Exception as e:
            log.exception("Error processing message: %s", e)
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"Error processing message: {e}"},
            )

    async def start(self) -> None:
        log.info("Starting bot...")

        log.info("Bot started")

    async def run_forever(self) -> None:
        await self.start()

        response = await self.client.sync()
        if isinstance(response, SyncResponse):
            log.info(
                "Initial sync complete, next_batch: %s",
                response.next_batch[:20] + "...",
            )

        self.client.add_event_callback(
            self.message_callback,  # pyright: ignore
            RoomMessageText,
        )

        try:
            while True:
                await self.client.sync()
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise

    async def stop(self) -> None:
        log.info("Stopping bot...")
        await self.client.close()
        log.info("Bot stopped")
