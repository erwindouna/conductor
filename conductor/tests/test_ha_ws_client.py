"""Test for the HA WebSocket client."""

import asyncio

import pytest

from conductor.ha_websocket import HA_WS_CLIENT_NAME, HAWebSocketClient, HAWebSocketError


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


async def test_client_connection(client: HAWebSocketClient) -> None:
    """Test connecting and authenticating the HA Websocket client."""
    client_init.start()
    try:
        await client_init.connect()
        assert client_init._ws is not None
    finally:
        await client_init.stop()
