"""Simple event bus implementation."""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BusMessage:
    """Main structure for the bus message."""

    topic: str
    payload: Any


class ConductorEventBus:
    """Simple event bus implementation."""

    def __init__(self, app: FastAPI, maxsize: int = 1000) -> None:
        """Initialize the event bus."""
        _LOGGER.info("Initializing Conductor event bus, with maxsize=%d", maxsize)
        self.app: FastAPI = app
        self._subs: dict[str, list[asyncio.Queue[BusMessage]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._maxsize = maxsize

    async def subscribe(self, topic: str) -> asyncio.Queue[BusMessage]:
        """Subscribe to a topic."""
        queue = asyncio.Queue(maxsize=self._maxsize)
        async with self._lock:
            self._subs[topic].append(queue)
            _LOGGER.debug("Subscribed to topic: %s", topic)
        return queue

    async def unsubscribe(self, topic: str, queue: asyncio.Queue[BusMessage]) -> None:
        """Unsubscribe from a topic."""
        async with self._lock:
            if topic in self._subs:
                self._subs[topic].remove(queue)
                if not self._subs[topic]:
                    _LOGGER.debug("No more subscribers for topic: %s, removing topic", topic)
                    del self._subs[topic]

    async def publish(self, topic: str, payload: Any) -> None:
        """Publish a message to a topic."""
        _LOGGER.debug("Publishing message to topic: %s", topic)
        async with self._lock:
            subscribers = list(self._subs.get(topic, []))

        msg = BusMessage(topic=topic, payload=payload)

        for queue in subscribers:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                _LOGGER.warning(
                    "Dropping message on topic %s (subscriber queue full)",
                    topic,
                )
