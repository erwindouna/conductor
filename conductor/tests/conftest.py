"""Fixtures for testing HAWebSocketClient with a mock Home Assistant WebSocket server."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

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
    app["received"] = []  # collected client->server JSON messages (post-auth, and anything else)
    app.router.add_get("/api/websocket", ha_ws_handler)
    return await aiohttp_server(app)


@pytest.fixture(name="client_init")
async def ha_ws_client_init(ha_ws_server: web.Server) -> AsyncGenerator[HAWebSocketClient, None]:
    """Return an HAWebSocketClient instance (configured), not connected/authenticated."""
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
async def ha_ws_client(client_init: HAWebSocketClient) -> AsyncGenerator[HAWebSocketClient, None]:
    """Main fixture: returns a started, connected, authenticated HAWebSocketClient."""
    client_init.start()
    await client_init.connect()
    await client_init.authenticate()
    return client_init
