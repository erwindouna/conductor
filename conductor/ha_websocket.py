"""Home Assistant WebSocket."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Self, cast

import aiohttp
from fastapi import FastAPI

from conductor.engine import ConductorEngine
from conductor.models.ha_ws import (
    AuthFrame,
    ResultFrame,
    SubscribeEventsFrame,
    WSBase,
    WSType,
    parse_incoming,
)

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

    def __init__(
        self,
        app: FastAPI,
        config: HAWebSocketClientConfig,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the handler."""
        self.app: FastAPI | None = app
        self.config: HAWebSocketClientConfig = config
        self._engine: ConductorEngine | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._session: aiohttp.ClientSession | None = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id: int = 0

    def start(self) -> None:
        """Start the connection."""
        if self._task is not None and not self._task.done():
            raise HAWebSocketError("Websocket client is already running")

        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=HA_WS_CLIENT_NAME)

    async def stop(self) -> None:
        """Stop the Websocket connection."""
        self._stop.set()
        if self._task:  # pragma: no cover
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError as err:
                _LOGGER.info("Websocket client task cancelled: %s", err)

        if self._ws and not self._ws.closed:
            await self._ws.close()  # pragma: no cover

        if self._session and not self._session.closed:
            await self._session.close()  # pragma: no cover
        _LOGGER.info("HA websocket client stopped")

    async def _run(self) -> None:
        """Main connection loop with reconnection logic."""
        backoff = 1.0
        max_backoff = 30.0

        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
                backoff = 1.0
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Connection timed out, retrying with backoff in %.1f seconds...", backoff
                )
            except asyncio.CancelledError as err:
                _LOGGER.warning("HA ws client task was cancelled: %s", err)
            except HAWebSocketError as err:
                _LOGGER.error("Websocket error: %s", err)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected websocket failure: %s", err)

            if self._stop.is_set():
                _LOGGER.info("Websocket client stopping, not reconnecting")
                break

            _LOGGER.info("Reconnecting in %.1f seconds...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)

    async def connect(self) -> None:
        """Connect to Home Assistant Websocket."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
        self._session = aiohttp.ClientSession(timeout=timeout)

        _LOGGER.info(
            "Connecting to %s, timeout set to %s seconds", self.config.ws_url, HA_WS_TIMEOUT
        )

        self._ws = await self._session.ws_connect(
            url=self.config.ws_url,
            heartbeat=30.0,  # Do ping/pong automatically
            autoping=True,
        )

    async def authenticate(self) -> None:
        """Authenticate to Home Assistant Websocket."""
        # Initial message should be auth_required
        first = await self._receive_message()
        if first.type != WSType.AUTH_REQUIRED:
            raise HAWebSocketAuthError(f"Unexpected response from Home Assistant: {first}")

        # Send access token
        await self._send_message(AuthFrame(type=WSType.AUTH, access_token=self.config.token))

        # Expect auth_ok or auth_invalid
        result = await self._receive_message()
        match result.type:
            case WSType.AUTH_OK:
                _LOGGER.info("Successfully authenticated to Home Assistant Websocket")
            case WSType.AUTH_INVALID:
                raise HAWebSocketAuthError(f"Auth failed: {result}")

    async def _connect_and_listen(self) -> None:
        """Connect to Home Assistant Websocket and listen for events."""
        await self.connect()
        await self.authenticate()

        # Wait for subscription confirmation
        sub_id = await self._subscribe_events()
        _LOGGER.info("Subscribed to %s (id=%d)", "state_changed", sub_id)

        # Listen for incoming messages
        ws = self._require_ws()
        async for ws_msg in ws:
            match ws_msg.type:
                case aiohttp.WSMsgType.TEXT:
                    await self._handle_message(
                        frame=cast(WSBase, parse_incoming(payload=json.loads(ws_msg.data)))
                    )
                case aiohttp.WSMsgType.ERROR:
                    raise HAWebSocketError(f"Websocket error: {ws.exception()}")
                case aiohttp.WSMsgType.CLOSED | aiohttp.WSMsgType.CLOSING:
                    raise HAWebSocketError("Websocket closed")

    async def _handle_message(self, frame: WSBase) -> None:
        """Handle incoming Websocket message parsed into a frame model."""
        if frame.type == WSType.RESULT:
            res = cast(ResultFrame, frame)
            if res.success is False:
                _LOGGER.warning("Command failed: %s", res.model_dump())
            await self.app.state.event_bus.publish(
                topic="TOPIC_HA_EVENT_RESULT",
                payload=res,
            )
            return

        if frame.type == WSType.EVENT:
            _LOGGER.debug("Received event: %s", frame.model_dump())
            # Finally publish the event to the event bus
            await self.app.state.event_bus.publish(
                topic="ha.event." + frame.event.event_type,
                payload=frame.event,
            )
            return

    async def _subscribe_events(self, event_type: str | None = None) -> int:
        """Subscribe to Home Assistant events of a given type."""
        self._msg_id += 1

        await self._send_message(
            SubscribeEventsFrame(
                id=self._msg_id,
                type=WSType.SUBSCRIBE_EVENTS,
                event_type=event_type,
            )
        )
        await self._receive_message()

        return self._msg_id

    async def _send_message(self, payload: Any) -> None:
        """Send a JSON message over the websocket."""
        ws = self._require_ws()
        data = payload
        if hasattr(payload, "model_dump"):
            # Exclude None values (for example: avoid sending id=None in auth message,
            # or the event_type is None)
            data = payload.model_dump(exclude_none=True)

        await ws.send_json(data)

    async def _receive_message(self) -> Any:
        """Receive and parse a JSON WS message into a frame model."""
        ws = self._require_ws()
        ws_msg = await ws.receive()
        match ws_msg.type:
            case aiohttp.WSMsgType.TEXT:
                payload = json.loads(ws_msg.data)
                return parse_incoming(payload)
            case aiohttp.WSMsgType.ERROR:
                raise HAWebSocketConnectionError(f"Websocket error: {ws.exception()}")
            case aiohttp.WSMsgType.CLOSED | aiohttp.WSMsgType.CLOSING:
                raise HAWebSocketError("Websocket closed")
            case _:
                raise HAWebSocketError(f"Unexpected websocket message type: {ws_msg.type}")

    def _require_ws(self) -> aiohttp.ClientWebSocketResponse:
        """Return an active websocket or raise a standardized connection error."""
        if self._ws is None or self._ws.closed:
            raise HAWebSocketConnectionError("Websocket not connected")
        return self._ws

    async def __aenter__(self) -> Self:
        """Support async with by starting on enter."""

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Ensure clean shutdown on exit from context manager."""
        await self.stop()


class HAWebSocketError(Exception):
    """Home Assistant Websocket error."""


class HAWebSocketAuthError(HAWebSocketError):
    """Home Assistant Websocket authentication error."""


class HAWebSocketConnectionError(HAWebSocketError):
    """Home Assistant Websocket connection error."""


class HAWebSocketTimeout(HAWebSocketError):
    """Home Assistant Websocket timeout error."""
