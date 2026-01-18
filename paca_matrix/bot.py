import logging

from nio import AsyncClient, MatrixRoom, RoomMessageText, SyncResponse  # type: ignore

log = logging.getLogger(__name__)


class EchoBot:
    def __init__(self, homeserver: str, user_id: str, access_token: str) -> None:
        self.client = AsyncClient(homeserver, user_id)
        self.client.access_token = access_token

    async def message_callback(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == self.client.user:
            return

        log.debug("Received message from %s: %s", event.sender, event.body)

        await self.client.room_send(
            room_id=room.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": event.body},
        )

        log.debug("Echoed message back to %s", room.room_id)

    async def start(self) -> None:
        log.info("Starting bot...")

        log.info("Bot started")

    async def run_forever(self) -> None:
        await self.start()

        response = await self.client.sync()
        if isinstance(response, SyncResponse):
            self.client.next_batch = response.next_batch
            log.info(
                "Initial sync complete, next_batch: %s",
                response.next_batch[:20] + "...",
            )

        self.client.add_event_callback(
            self.message_callback,  # pyright: ignore
            RoomMessageText,
        )

        while True:
            response = await self.client.sync()
            if isinstance(response, SyncResponse):
                self.client.next_batch = response.next_batch

    async def stop(self) -> None:
        log.info("Stopping bot...")
        await self.client.close()
        log.info("Bot stopped")
