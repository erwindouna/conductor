"""Engine class. Let's conduct some work!"""

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)


class ConductorEngine:
    """Conductor engine class."""

    def __init__(self) -> None:
        """Initialize the engine."""
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        """Start the engine."""
        _LOGGER.info("Starting Conductor engine")
        if self._task is not None and not self._task.done():
            raise ConductorEngineRuntimeError("Engine is already running")

        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="conductor-engine")
        _LOGGER.info("Conductor engine started")

    async def stop(self) -> None:
        """Stop the engine."""
        _LOGGER.info("Stopping Conductor engine")
        self._stop.set()
        if self._task:  # pragma: no cover
            self._task.cancel()
        _LOGGER.info("Conductor engine stopped")

    async def _run(self) -> None:
        """Engine main loop."""

        while not self._stop.is_set():
            try:
                _LOGGER.info("Sleeping for 1 second in engine loop")
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                _LOGGER.info("Conductor engine task was cancelled")

            if self._stop.is_set():
                _LOGGER.info("Conductor engine stopping as requested")
                break


class ConductorEngineError(Exception):
    """Conductor engine error."""


class ConductorEngineRuntimeError(ConductorEngineError):
    """Generic conductor engine error."""
