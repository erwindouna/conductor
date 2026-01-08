"""Fixtures for testing HAWebSocketClient with a mock Home Assistant WebSocket server."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession, WSMsgType, web

from conductor.ha_websocket import HAWebSocketClient, HAWebSocketClientConfig

from . import load_fixtures


async def ha_ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Mock Home Assistant WebSocket handler for testing."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    await ws.send_json(json.loads(load_fixtures("auth_required.json")))

    msg = await ws.receive()
    assert msg.type == WSMsgType.TEXT
    payload = json.loads(msg.data)
    assert payload["type"] == "auth"
    assert "access_token" in payload

    await ws.send_json(json.loads(load_fixtures("auth_ok.json")))

    # Keep the socket open so the test client can continue using it.
    # Record anything the client sends for optional assertions.
    received: list[dict[str, Any]] = request.app["received"]
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                received.append(json.loads(msg.data))
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        # See if it helps avoid "unclosed client session" warnings
        await ws.close()

    return ws


@pytest.fixture(name="ha_ws_server")
async def ha_ws_server(aiohttp_server) -> web.Server:
    """Return a mock Home Assistant WebSocket server."""
    app = web.Application()
    app["received"] = []
    app.router.add_get("/api/websocket", ha_ws_handler)
    return await aiohttp_server(app)


@pytest.fixture(name="client_init")
async def ha_ws_client_init(ha_ws_server: web.Server) -> AsyncGenerator[HAWebSocketClient, None]:
    """Return a configured HAWebSocketClient, not connected/authenticated."""
    async with (
        ClientSession() as session,
        HAWebSocketClient(
            config=HAWebSocketClientConfig(
                ws_url=str(ha_ws_server.make_url("/api/websocket")),
                token="test_token",
            ),
            session=session,
        ) as client,
    ):
        yield client


@pytest.fixture(name="client")
async def mock_ha_ws_client() -> AsyncGenerator[HAWebSocketClient, None]:
    """Mocked HAWebSocketClient with controllable methods and websocket stub."""

    async with HAWebSocketClient(
        HAWebSocketClientConfig(ws_url="ws://homeassistant/api/websocket", token="test_token")
    ) as client:
        setattr(client, "connect", AsyncMock(return_value=None))
        setattr(client, "authenticate", AsyncMock(return_value=None))
        setattr(client, "_subscribe_events", AsyncMock(return_value=1))

        class _WSStub:
            """Stub websocket to simulate aiohttp ClientWebSocketResponse.""" ""

            closed = False

            def __init__(self, messages: list[Any] | None = None) -> None:
                """Initialize the stub."""
                self._messages = messages or []

            async def send_json(self, _: Any) -> None:
                """Simulate sending a JSON message over the websocket."""
                return None

            def exception(self):
                """Simulate checking for websocket exceptions."""
                return None

            async def close(self) -> None:
                """Close it."""
                self.closed = True

            def __aiter__(self):
                """Return an async iterator over the preset messages."""

                async def _gen():
                    """Async generator yielding preset messages."""
                    for m in self._messages:
                        yield m

                return _gen()

        def set_ws_messages(messages: list[Any]) -> None:
            """Set the messages which can be yielded. Hooray, this works!"""
            client._ws = _WSStub(messages)

        def set_ws_error(exc: Exception) -> None:
            """Set an exception to be raised by the stub websocket."""
            ws = _WSStub([])

            def _exc():
                """Return the preset exception."""
                # It needs to be a function to avoid not being raised
                return exc

            setattr(ws, "exception", _exc)
            client._ws = ws

        setattr(client, "set_ws_messages", set_ws_messages)
        setattr(client, "set_ws_error", set_ws_error)

        yield client
