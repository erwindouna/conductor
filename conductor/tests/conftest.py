"""Conftest for the pyportainer tests."""

from collections.abc import AsyncGenerator

import pytest
from aiohttp import ClientSession

from conductor.ha_websocket import HAWebSocketClient, HAWebSocketClientConfig


@pytest.fixture(name="ha_ws_client")
async def ha_ws_client() -> AsyncGenerator[ClientSession, None]:
    """Return an aiohttp client session."""
    async with (
        ClientSession(),
        HAWebSocketClient(
            HAWebSocketClientConfig(ws_url="ws://localhost:8123/api/websocket", token="test_token")
        ) as ha_ws_client,
    ):
        yield ha_ws_client
