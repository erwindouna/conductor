"""Conductor application"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from conductor.logger import setup_logging

from .bus import ConductorEventBus
from .engine import ConductorEngine
from .ha_websocket import HAWebSocketClient, HAWebSocketClientConfig

# Yeah, I know... just for testing purposes.
test_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI4OWM1OWRmZWM0ZGM0YTlkOTE0YTRkMDIwNzI4MWY0YyIsImlhdCI6MTc2NzgyNTYzNCwiZXhwIjoyMDgzMTg1NjM0fQ.VSr2Xakx85_OeUFtK5qdOcS14VvzmrpMX5fzOvrBIGg"  # pylint: disable=line-too-long, invalid-name
test_url = "ws://192.168.2.53:8123/api/websocket"  # pylint: disable=invalid-name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for Conductor."""
    setup_logging()
    logger = logging.getLogger("conductor")
    logger.info("Starting Conductor application")

    # Start the event bus
    app.state.event_bus = ConductorEventBus(app)

    # Start the Home Assistant Websocket client
    ha_ws_config = HAWebSocketClientConfig(
        ws_url=test_url,
        token=test_token,
    )
    ha_ws_client = HAWebSocketClient(app, config=ha_ws_config)
    app.state.ha_ws_client = ha_ws_client
    app.state.ha_ws_client.start()

    # Start the Conductor engine
    conductor_engine = ConductorEngine(app)
    app.state.conductor_engine = conductor_engine
    app.state.conductor_engine.start()

    try:
        yield
    finally:
        logger.info("Stopping Home Assistant Websocket client")
        await ha_ws_client.stop()
        await conductor_engine.stop()
    logger.info("Shutting down Conductor application")


app = FastAPI(lifespan=lifespan)
