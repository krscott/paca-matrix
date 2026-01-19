import logging

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

    async def send_to_matrix(self, room: MatrixRoom, message: str) -> None:
        await self.matrix_bot.send_message(room, message)

    async def message_callback(self, room: MatrixRoom, event: Event) -> None:
        if not isinstance(event, RoomMessageText):
            return
        if event.sender == self.matrix_bot.client.user:
            return

        log.info("Received from %s: %s", event.sender, event.body)

        message_parts: list[str] = []
        prev_update_type = ""

        try:
            async for update in self.opencode_client.prompt_stream(event.body):
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
            await self.matrix_bot.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"Error processing message: {e}"},
            )

    async def run_forever(self) -> None:
        log.info("Starting bot...")
        await self.opencode_client.start()
        await self.matrix_bot.setup_message_handler(self.message_callback)
        log.info("Bot started")

        await self.matrix_bot.sync_forever()

    async def stop(self) -> None:
        log.info("Stopping bot...")
        await self.opencode_client.stop()
        await self.matrix_bot.stop()
        log.info("Bot stopped")
