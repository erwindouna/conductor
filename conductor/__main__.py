"""Conductor application"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from conductor.logger import setup_logging

from .ha_websocket import HAWebSocketClient, HAWebSocketClientConfig

# Yeah, I know... just for testing purposes.
test_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI4OWM1OWRmZWM0ZGM0YTlkOTE0YTRkMDIwNzI4MWY0YyIsImlhdCI6MTc2NzgyNTYzNCwiZXhwIjoyMDgzMTg1NjM0fQ.VSr2Xakx85_OeUFtK5qdOcS14VvzmrpMX5fzOvrBIGg"  # pylint: disable=line-too-long, invalid-name
test_url = "ws://192.168.2.53:8123/api/websocket"  # pylint: disable=invalid-name


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for Conductor."""
    setup_logging()
    logger = logging.getLogger("conductor")
    logger.info("Starting Conductor application")

    ha_ws_config = HAWebSocketClientConfig(
        ws_url=test_url,
        token=test_token,
    )
    ha_ws_client = HAWebSocketClient(config=ha_ws_config)
    ha_ws_client.start()

    try:
        yield
    finally:
        logger.info("Stopping Home Assistant Websocket client")
        await ha_ws_client.stop()
    logger.info("Shutting down Conductor application")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
