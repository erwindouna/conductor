"""Test for the HA WebSocket client."""

import asyncio
import logging
from unittest.mock import AsyncMock

import aiohttp
import pytest

from conductor.ha_websocket import (
    HA_WS_CLIENT_NAME,
    HAWebSocketAuthError,
    HAWebSocketClient,
    HAWebSocketError,
)
from conductor.models.ha_ws import AuthOk, WSType


async def test_init_client(client_init: HAWebSocketClient) -> None:
    """Test initializing the HA Websocket client."""
    client_init.start()
    try:
        assert isinstance(client_init._task, asyncio.Task)
        assert client_init._task.get_name() == HA_WS_CLIENT_NAME
        assert not client_init._task.done()
    finally:
        await client_init.stop()


async def test_init_client_already_running(client_init: HAWebSocketClient) -> None:
    """Test initializing the HA Websocket client."""

    # Simulate already running client
    started = asyncio.Event()
    gatekeeper = asyncio.Event()

    async def dummy_task() -> None:
        """Dummy task to simulate running client."""
        started.set()
        await gatekeeper.wait()  # Just need to wait, so we can test

    client_init._run = dummy_task

    # Try a new start while the dummy task is running
    client_init.start()
    await asyncio.wait_for(started.wait(), timeout=1)

    with pytest.raises(HAWebSocketError, match="Websocket client is already running"):
        client_init.start()

    gatekeeper.set()
    await client_init.stop()


async def test_client_connection(client_init: HAWebSocketClient) -> None:
    """Test connecting and authenticating the HA Websocket client."""
    try:
        await client_init.connect()
        assert client_init._ws is not None
        assert isinstance(client_init._ws, aiohttp.ClientWebSocketResponse)
        assert not client_init._ws.closed
    finally:
        await client_init.stop()


async def test_client_authentication(
    client_init: HAWebSocketClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Test authenticating the HA Websocket client."""
    try:
        caplog.set_level(logging.INFO, logger="conductor.ha_websocket")
        await client_init.connect()
        await client_init.authenticate()

        assert "Successfully authenticated to Home Assistant Websocket" in caplog.text
    finally:
        await client_init.stop()


async def test_client_authentication_unexpected_first_frame(client_init: HAWebSocketClient) -> None:
    """Test if the first frame isn't auth_required. Don't know why, but let's be thorough."""
    client_init._receive_message = AsyncMock(return_value=AuthOk(type=WSType.AUTH_OK))
    client_init._send_message = AsyncMock()

    with pytest.raises(HAWebSocketAuthError, match="Unexpected response from Home Assistant"):
        await client_init.authenticate()

    client_init._send_message.assert_not_called()
