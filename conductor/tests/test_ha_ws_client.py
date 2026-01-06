"""Test for the HA WebSocket client."""

from aiohttp import ClientSession


async def test_init_client() -> None:
    """Test initializing the HA WebSocket client."""
    async with ClientSession() as session:
        ha_ws_client._session = session  # type: ignore[attr-defined]
        assert ha_ws_client._session is session
