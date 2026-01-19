import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class OpencodeClient:
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
