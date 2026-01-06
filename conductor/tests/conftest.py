"""Conftest for the pyportainer tests."""

import json
from collections.abc import AsyncGenerator

import pytest
from aiohttp import ClientSession, WSMsgType, web

from conductor.ha_websocket import HAWebSocketClient, HAWebSocketClientConfig

from . import load_fixtures


async def ha_ws_handler(request: web.Request) -> web.WebSocketResponse:
    """A mock Home Assistant Websocket handler for testing."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    await ws.send_json(load_fixtures("auth_required.json"))

    msg = await ws.receive()
    assert msg.type == WSMsgType.TEXT
    payload = json.loads(msg.data)
    assert payload["type"] == "auth"
    assert "access_token" in payload

    await ws.send_json(load_fixtures("auth_ok.json"))

    return ws


@pytest.fixture(name="ha_ws_server")
async def ha_ws_server(aiohttp_server) -> web.Server:
    """Return a mock Home Assistant Websocket server."""
    app = web.Application()
    app.router.add_get("/api/websocket", ha_ws_handler)
    server = await aiohttp_server(app)
    return server


@pytest.fixture(name="client_init")
async def ha_ws_client_init(ha_ws_server: web.Server) -> AsyncGenerator[HAWebSocketClient, None]:
    """Return an aiohttp client session, with HAWebSocketClient initialized."""
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
async def ha_ws_client() -> AsyncGenerator[HAWebSocketClient, None]:
    """Return including a started and authenticated HAWebSocketClient."""
    async with (
        ClientSession() as session,
        HAWebSocketClient(
            config=HAWebSocketClientConfig(
                ws_url="ws://localhost:8123/api/websocket",
                token="test_token",
            ),
            session=session,
        ) as client,
    ):
        client.start()
        await client.connect()
        await client.authenticate()
        yield client
