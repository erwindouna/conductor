"""Home Assistant WebSocket."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

@dataclass
class HAWebSocketClientConfig:
    """Configuration for Home Assistant WebSocket."""

    ws_url: str
    token: str

class HAWebSocketClient:
    """Home Assistant WebSocket handler."""

    def __init__(self, config: HAWebSocketClientConfig)-> None:
        """Initialize the WebSocket handler."""
        self.config = config
        self._task: asyncio.Task[None] | None= None
        self._stop = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id = 0

    def start(self) -> None:
        """Start the WebSocket connection."""
        if self._task is not None and not self._task.done():
            _LOGGER.error("WebSocket client is already running")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="ha-ws-client")

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError as err:
                raise HAWebSocketError("WebSocket task was cancelled") from err

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._session and not self._session.closed:
            await self._session.close()

    async def _run(self) -> None:
        """Main connection loop with reconnection logic."""
        backoff = 1.0
        max_backoff = 30.0

        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
                backoff = 1.0
            except asyncio.TimeoutError:
                _LOGGER.warning("Connection timed out, retrying with backoff in %.1f seconds...", backoff)
            except asyncio.CancelledError as err:
                _LOGGER.warning("HA ws client task was cancelled: %s", err)
            except Exception as err:
                _LOGGER.exception("WebSocket connection error: %s", err)
                raise HAWebSocketError("WebSocket connection error") from err
    
            if self._stop.is_set():
                _LOGGER.info("Websocket client stopping, not reconnecting")
                break

            _LOGGER.info("Reconnecting in %.1f seconds...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)

    async def _connect_and_listen(self) -> None:
        """Connect to Home Assistant WebSocket and listen for events."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
        self._session = aiohttp.ClientSession(timeout=timeout)

        _LOGGER.info("Connecting to %s", self.config.ws_url)
        self._ws = await self._session.ws_connect(
            url=self.config.ws_url,
            heartbeat=30.0,  # Do ping/pong automatically
            autoping=True,
            timeout=10.0,
        )

        # First check if we get the "auth_required"
        msg = await self._receive_message()
        if msg.get("type") != "auth_required":
            raise HAWebSocketError(f"Unexpected response from Home Assistant: {msg}")

        # Now send the auth message
        await self._send_message({"type": "auth", "access_token": self.config.token})

        # Wait for auth_ok
        msg = await self._receive_message()
        if msg.get("type") != "auth_ok":
            raise HAWebSocketError(f"Auth failed: {msg}")

        _LOGGER.info("Authenticated to Home Assistant WebSocket")

        # Wait for subscription confirmation
        sub_id = await self._subscribe_events("state_changed")
        _LOGGER.info("Subscribed to %s (id=%d)", "state_changed", sub_id)

        # Listen for incoming messages
        async for ws_msg in self._ws:
            match ws_msg.type:
                case aiohttp.WSMsgType.TEXT:
                    data = json.loads(ws_msg.data)
                    await self._handle_message(data)
                case aiohttp.WSMsgType.ERROR:
                    raise HAWebSocketError(f"Websocket error: {self._ws.exception()}")
                case aiohttp.WSMsgType.CLOSED | aiohttp.WSMsgType.CLOSING:
                    raise HAWebSocketError("Websocket closed")  

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming Websocket message."""
        msg_type = data.get("type")

        if msg_type == "event":
            event = data.get("event", {})
            ev_type = event.get("event_type")
            ev_data = event.get("data", {})
            # Example: print entity_id changes
            entity_id = ev_data.get("entity_id")
            if entity_id:
                _LOGGER.info("%s: %s", ev_type, entity_id)
            return

        if "id" in data and data.get("success") is False:
            _LOGGER.warning("Command failed: %s", data)
            return



    async def _subscribe_events(self, event_type: str) -> int:
        self._msg_id += 1
        msg_id = self._msg_id
        await self._send_message(
            {
                "id": msg_id,
                "type": "subscribe_events",
                "event_type": event_type,
            }
        )
        resp = await self._receive_message()
        if resp.get("id") != msg_id or not resp.get("success"):
            raise HAWebSocketError(f"Subscribe failed: {resp}")
        return msg_id

    async def _send_message(self, payload: dict[str, Any]) -> None:
        """Send a JSON message over the websocket."""
        await self._ws.send_str(json.dumps(payload))

    async def _receive_message(self) -> dict[str, Any]:
        """Receive a message from the websocket."""
        msg = await self._ws.receive()

        match msg.type:
            case aiohttp.WSMsgType.TEXT:
                return json.loads(msg.data)
            case aiohttp.WSMsgType.ERROR:
                raise HAWebSocketError(f"Websocket error: {self._ws.exception()}")
            case _:
                raise HAWebSocketError(f"Unexpected websocket message type: {msg.type}")
    
class HAWebSocketError(Exception):
    """Home Assistant WebSocket error."""