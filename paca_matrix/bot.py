import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from nio import (
    AsyncClient,
    AsyncClientConfig,
    Event,
    MatrixRoom,
    RoomMessageText,
    SyncResponse,
)

log = logging.getLogger(__name__)

OPENCODE_MODEL = "opencode/glm-4.7-free"


class ACPClient:
    """Client for communicating with OpenCode via Agent Client Protocol (ACP)"""

    def __init__(self, cwd: str | None = None) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        self.request_id = 0
        self.cwd = cwd or str(Path.cwd())

    async def start(self) -> None:
        log.info("Starting OpenCode ACP process...")
        self.process = await asyncio.create_subprocess_exec(
            "opencode",
            "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        asyncio.create_task(self._log_stderr())

        log.debug("Sending initialize request...")
        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {
                        "readTextFile": True,
                        "writeTextFile": True,
                    },
                    "terminal": True,
                },
                "clientInfo": {
                    "name": "paca-matrix",
                    "title": "Paca Matrix Bot",
                    "version": "0.1.0",
                },
            },
        )

        log.info(
            "Initialized OpenCode: %s",
            result.get("agentInfo", {}).get("name", "Unknown"),
        )

        log.debug("Sending session/new request...")
        session_result = await self._send_request(
            "session/new",
            {
                "cwd": self.cwd,
                "mcpServers": [],
            },
        )

        self.session_id = session_result["sessionId"]
        log.info("Created session: %s", self.session_id)

    async def _log_stderr(self) -> None:
        if not self.process or not self.process.stderr:
            return
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            log.debug("OpenCode stderr: %s", line.decode().strip())

    async def prompt_stream(self, message: str) -> AsyncIterator[dict[str, Any]]:
        if not self.session_id:
            raise RuntimeError("Session not initialized")

        prompt_id = self.request_id
        self.request_id += 1

        prompt_request = {
            "jsonrpc": "2.0",
            "id": prompt_id,
            "method": "session/prompt",
            "params": {
                "sessionId": self.session_id,
                "prompt": [
                    {
                        "type": "text",
                        "text": message,
                    }
                ],
            },
        }

        await self._write_message(prompt_request)

        while True:
            msg = await self._read_message()
            if msg.get("id") == prompt_id:
                return
            if msg.get("method") == "session/update":
                params = msg.get("params", {})
                if params.get("sessionId") == self.session_id:
                    yield cast(dict[str, Any], params)
            elif msg.get("method") == "session/end":
                return

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        request_id = self.request_id
        self.request_id += 1

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        await self._write_message(request)

        while True:
            response = await self._read_message()
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(f"ACP error: {response['error']}")
                result: dict[str, Any] = response.get("result", {})
                return result

    async def _write_message(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Process not started")

        data = json.dumps(message)
        log.debug("Sending JSON: %s", data)
        self.process.stdin.write((data + "\n").encode())
        await self.process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise RuntimeError("Process not started")

        line_bytes = await self.process.stdout.readline()
        if not line_bytes:
            raise RuntimeError("Process closed unexpectedly")

        line = line_bytes.decode().strip()
        log.debug("Received: %s", line)
        msg = json.loads(line)
        assert isinstance(msg, dict)
        return cast(dict[str, Any], msg)

    async def stop(self) -> None:
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.process.kill()
                    await self.process.wait()
                except ProcessLookupError:
                    pass
            finally:
                self.process = None
                log.info("Stopped OpenCode ACP process")


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
        self.acp_client = ACPClient()

    async def message_callback(self, room: MatrixRoom, event: Event) -> None:
        if not isinstance(event, RoomMessageText):
            return
        if event.sender == self.client.user:
            return

        log.info("Received from %s: %s", event.sender, event.body)

        try:
            message_parts: list[str] = []
            async for update in self.acp_client.prompt_stream(event.body):
                log.debug(str(update))
                update_type = update.get("update", {}).get("sessionUpdate")

                if update_type == "agent_message_chunk":
                    content = update.get("update", {}).get("content", {})
                    if content.get("type") == "text":
                        text = content.get("text", "")
                        assert isinstance(text, str)
                        message_parts.append(text)

                elif update_type == "plan":
                    entries = update.get("update", {}).get("entries", [])
                    plan_text = "\n".join(
                        f"- {e.get('content', '')}" for e in entries if e.get("content")
                    )
                    if plan_text:
                        message_parts.append(f"**Plan:**\n{plan_text}")

                elif update_type == "tool_call":
                    title = update.get("title", "Tool call")
                    status = update.get("status", "pending")
                    message_parts.append(f"**{title}**: {status}")

                elif update_type == "tool_call_update":
                    status = update.get("status", "pending")
                    content_list = update.get("content", [])
                    if status == "completed" and content_list:
                        content = content_list[0].get("content", {})
                        if content.get("type") == "text":
                            message_parts.append(content.get("text", ""))

            if message_parts:
                response = "".join(message_parts).strip()
            else:
                response = "No response from OpenCode"

            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": response},
            )

            log.info("Sending to %s: %s", room.room_id, response)
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
