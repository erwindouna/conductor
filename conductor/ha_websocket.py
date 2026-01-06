"""Home Assistant WebSocket."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from conductor.models.ha_ws import AuthFrame, WSType, parse_incoming

_LOGGER = logging.getLogger(__name__)

HA_WS_TIMEOUT = 10
HA_WS_CLIENT_NAME = "conductor-ha-ws-client"

@dataclass
class HAWebSocketClientConfig:
    """Configuration for Home Assistant WebSocket."""

    ws_url: str
    token: str

class HAWebSocketClient:
    """Home Assistant WebSocket handler."""

    def __init__(self, config: HAWebSocketClientConfig)-> None:
        """Initialize the WebSocket handler."""
        self.config: HAWebSocketClientConfig = config
        self._task: asyncio.Task[None] | None= None
        self._stop = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id: int = 0

    def start(self) -> None:
        """Start the Websocket connection."""
        if self._task is not None and not self._task.done():
            _LOGGER.error("Websocket client is already running")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=HA_WS_CLIENT_NAME)

    async def stop(self) -> None:
        """Stop the Websocket connection."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError as err:
                raise HAWebSocketError("Websocket task was cancelled") from err

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

    async def connect(self) -> None:
        """Connect to Home Assistant WebSocket."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
        self._session = aiohttp.ClientSession(timeout=timeout)

        _LOGGER.info("Connecting to %s, timeout set to %s seconds", self.config.ws_url, HA_WS_TIMEOUT)
        self._ws = await self._session.ws_connect(
            url=self.config.ws_url,
            heartbeat=30.0,  # Do ping/pong automatically
            autoping=True,
        )

    async def authenticate(self) -> None:
        """Authenticate to Home Assistant WebSocket."""
        frame = await self._receive_message()
        if frame.type != WSType.AUTH_REQUIRED:
            raise HAWebSocketAuthError(f"Unexpected response from Home Assistant: {frame}")

        await self._send_message(AuthFrame(
            type=WSType.AUTH,
            access_token=self.config.token,
        ))

        frame = await self._receive_message()
        if frame.type != WSType.AUTH_OK:
            raise HAWebSocketAuthError(f"Auth failed: {frame}")

        _LOGGER.info("Authenticated to Home Assistant WebSocket")

    async def _connect_and_listen(self) -> None:
        """Connect to Home Assistant WebSocket and listen for events."""
        await self.connect()
        await self.authenticate()

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
        if data.type == WSType.EVENT:
            event = data.get("event", {})
            ev_type = event.get("event_type")
            ev_data = event.get("data", {})
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
        frame = parse_incoming(json.loads(msg.data))

        match frame.type:
            case aiohttp.WSMsgType.TEXT:
                return json.loads(frame.data)
            case aiohttp.WSMsgType.ERROR:
                raise HAWebSocketConnectionError(f"Websocket error: {self._ws.exception()}")
            case _:
                raise HAWebSocketError(f"Unexpected websocket message type: {frame.type}")
    
class HAWebSocketError(Exception):
    """Home Assistant WebSocket error."""

class HAWebSocketAuthError(HAWebSocketError):
    """Home Assistant WebSocket authentication error."""

class HAWebSocketConnectionError(HAWebSocketError):
    """Home Assistant WebSocket connection error."""

class HAWebSocketTimeout(HAWebSocketError):
    """Home Assistant WebSocket timeout error."""