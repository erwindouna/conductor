"""Conductor application"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
from conductor.logger import setup_logging

from .ha_websocket import HAWebSocketClient, HAWebSocketClientConfig

# Yeah, I know... just for testing purposes.
test_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJmZDhhNjY2ZjhkNGI0Y2Y3OGViMGYzM2QxZmY2ZGRkYiIsImlhdCI6MTc2NzY1MTM2NywiZXhwIjoyMDgzMDExMzY3fQ.Hi--sFVdhrjECMCH3xCHc0_ojmhc0Hj57Viq_lh-ZoI"
test_url = "ws://192.168.2.53:8123/api/websocket"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for Conductor."""
    setup_logging()
    _LOGGER = logging.getLogger("conductor")
    _LOGGER.info("Starting Conductor application")

    ha_ws_config = HAWebSocketClientConfig(
        ws_url=test_url,
        token=test_token,
    )
    ha_ws_client = HAWebSocketClient(config=ha_ws_config)
    ha_ws_client.start()

    try:
        yield
    finally:
        _LOGGER.info("Stopping Home Assistant WebSocket client")
        await ha_ws_client.stop()
    _LOGGER.info("Shutting down Conductor application")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
