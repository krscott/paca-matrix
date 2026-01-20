import asyncio
import json
import logging
import ssl
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class SSEEvent:
    """Represents a Server-Sent Event."""

    def __init__(
        self,
        event: str = "message",
        data: str = "",
        id: str | None = None,
        retry: int | None = None,
    ) -> None:
        self.event = event
        self.data = data
        self.id = id
        self.retry = retry

    def json(self) -> Any:
        """Parse the data field as JSON."""
        return json.loads(self.data)


class OpencodeClient:
    """Client for communicating with OpenCode via HTTP"""

    def __init__(
        self,
        server_url: str,
        session_name: str | None = None,
        model: str | None = None,
    ) -> None:
        self.session_id: str | None = None
        self.server_url = server_url
        self.session_name = session_name
        self.http_session: aiohttp.ClientSession | None = None
        self.model: str | None = model

    async def start(self) -> None:
        await self._start_http()

    async def _start_http(self) -> None:
        log.info("Connecting to OpenCode server at %s...", self.server_url)

        # Create SSL context with verification enabled (default behavior enforced)
        # For localhost/127.0.0.1 connections, we allow unverified SSL since
        # the server is typically running on the same machine
        ssl_context: ssl.SSLContext | bool
        if self.server_url.startswith("http://"):
            # HTTP connection, no SSL needed
            ssl_context = False
        elif "127.0.0.1" in self.server_url or "localhost" in self.server_url:
            # Localhost HTTPS connection - allow self-signed certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            log.warning(
                "SSL verification disabled for localhost connection: %s",
                self.server_url,
            )
        else:
            # External HTTPS connection - enforce full TLS verification
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            log.info("SSL verification enabled for connection to: %s", self.server_url)

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.http_session = aiohttp.ClientSession(connector=connector)

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

    async def prompt_async(self, message: str) -> None:
        """Send a message to OpenCode without waiting for a response.

        The response will arrive via the SSE event stream.
        """
        if not self.session_id or not self.http_session or not self.server_url:
            raise RuntimeError("HTTP session not initialized")

        url = f"{self.server_url}/session/{self.session_id}/prompt_async"
        log.debug("Sending async message to: %s", url)

        body: dict[str, Any] = {"parts": [{"type": "text", "text": message}]}

        if self.model:
            if "/" in self.model:
                provider_id, model_id = self.model.split("/", 1)
                body["model"] = {"providerID": provider_id, "modelID": model_id}
            else:
                body["model"] = self.model

        async with self.http_session.post(
            url,
            json=body,
        ) as resp:
            if resp.status != 204:
                text = await resp.text()
                raise RuntimeError(f"HTTP error {resp.status}: {text}")

        log.debug("Async message sent successfully")

    async def get_message_parts(self, message_id: str) -> list[str]:
        """Get all text parts for a message from the session."""
        if not self.session_id or not self.http_session or not self.server_url:
            raise RuntimeError("HTTP session not initialized")

        url = f"{self.server_url}/session/{self.session_id}/message/{message_id}"
        log.debug("Fetching message parts from: %s", url)

        async with self.http_session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP error {resp.status}: {text}")

            message_data = await resp.json()

        # Extract text parts
        parts: list[str] = []
        parts_data = message_data.get("parts", [])
        for part in parts_data:
            if part.get("type") == "text":
                text = part.get("text", "")
                if isinstance(text, str) and text:
                    parts.append(text)

        return parts

    async def subscribe_events(self) -> AsyncIterator[SSEEvent]:
        """Subscribe to the SSE event stream from OpenCode.

        Yields SSEEvent objects as they arrive from the server.
        Automatically reconnects on connection failures.
        """
        if not self.http_session or not self.server_url:
            raise RuntimeError("HTTP session not initialized")

        url = f"{self.server_url}/event"
        retry_delay = 1.0
        max_retry_delay = 30.0

        while True:
            try:
                log.info("Connecting to SSE stream: %s", url)
                async with self.http_session.get(
                    url,
                    headers={"Accept": "text/event-stream"},
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(
                            f"SSE connection failed: {resp.status} {text}"
                        )

                    log.info("Connected to SSE stream")
                    retry_delay = 1.0  # Reset on successful connection

                    async for event in self._parse_sse_stream(resp):
                        yield event

            except asyncio.CancelledError:
                log.info("SSE subscription cancelled")
                raise
            except Exception as e:
                log.warning(
                    "SSE connection error: %s, reconnecting in %.1fs", e, retry_delay
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _parse_sse_stream(
        self, resp: aiohttp.ClientResponse
    ) -> AsyncIterator[SSEEvent]:
        """Parse an SSE stream from an aiohttp response."""
        event_type = "message"
        data_lines: list[str] = []
        event_id: str | None = None
        retry: int | None = None

        async for line_bytes in resp.content:
            line = line_bytes.decode("utf-8").rstrip("\r\n")

            if line.startswith(":"):
                # Comment, ignore
                continue
            elif line == "":
                # Empty line = dispatch event
                if data_lines:
                    data = "\n".join(data_lines)
                    yield SSEEvent(
                        event=event_type, data=data, id=event_id, retry=retry
                    )
                # Reset for next event
                event_type = "message"
                data_lines = []
                event_id = None
                retry = None
            elif ":" in line:
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]

                if field == "event":
                    event_type = value
                elif field == "data":
                    data_lines.append(value)
                elif field == "id":
                    event_id = value
                elif field == "retry":
                    try:
                        retry = int(value)
                    except ValueError:
                        pass
            else:
                # Field with no value
                if line == "data":
                    data_lines.append("")

    async def reply_question(self, request_id: str, answers: list[list[str]]) -> None:
        """Reply to a question request from OpenCode."""
        if not self.http_session or not self.server_url:
            raise RuntimeError("HTTP session not initialized")

        url = f"{self.server_url}/question/{request_id}/reply"
        log.debug("Replying to question: %s", url)

        body = {"answers": answers}

        async with self.http_session.post(
            url,
            json=body,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP error {resp.status}: {text}")

        log.debug("Question reply submitted successfully")

    async def abort_session(self) -> None:
        """Abort the current running session."""
        if not self.session_id or not self.http_session or not self.server_url:
            raise RuntimeError("HTTP session not initialized")

        url = f"{self.server_url}/session/{self.session_id}/abort"
        log.debug("Aborting session: %s", url)

        async with self.http_session.post(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP error {resp.status}: {text}")

        log.info("Session aborted successfully")

    async def stop(self) -> None:
        if self.http_session:
            await self.http_session.close()
            self.http_session = None
            log.info("Closed OpenCode HTTP session")
