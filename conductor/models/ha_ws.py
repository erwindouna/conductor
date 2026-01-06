"""Models for the Home Assistant WebSocket integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class WSType(StrEnum):
    """Home Assistant Websocket frame types."""

    EVENT = "event"
    RESULT = "result"
    AUTH = "auth"
    AUTH_OK = "auth_ok"
    AUTH_REQUIRED = "auth_required"
    AUTH_INVALID = "auth_invalid"
    SUBSCRIBE_EVENTS = "subscribe_events"


TModel = TypeVar("TModel", bound=type[BaseModel])
FRAME_REGISTRY: dict[WSType, type[BaseModel]] = {}


def register_frame(frame_type: WSType) -> TModel:
    """Decorator to register a WebSocket frame model by its `type`."""

    def decorator(model: type[BaseModel]) -> type[BaseModel]:
        FRAME_REGISTRY[frame_type] = model
        return model

    return decorator


class IncomingFrame(BaseModel):
    """Minimal envelope used to route to the correct concrete model."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    type: WSType


class WSBase(IncomingFrame):
    """Base model for concrete Home Assistant WebSocket frames."""

    model_config = ConfigDict(extra="forbid")


@register_frame(WSType.AUTH)
class AuthFrame(WSBase):
    """Home Assistant auth message."""

    type: WSType = WSType.AUTH
    access_token: str


@register_frame(WSType.AUTH_REQUIRED)
class AuthRequired(WSBase):
    """Home Assistant auth required message."""

    type: WSType = WSType.AUTH_REQUIRED
    ha_version: str | None = None


@register_frame(WSType.AUTH_OK)
class AuthOk(WSBase):
    """Home Assistant auth ok message."""

    type: WSType = WSType.AUTH_OK
    ha_version: str | None = None


@register_frame(WSType.AUTH_INVALID)
class AuthInvalid(WSBase):
    """Home Assistant auth invalid message."""

    type: WSType = WSType.AUTH_INVALID
    message: str | None = None


class WSError(BaseModel):
    """Error object embedded in a result frame."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = None
    message: str | None = None


@register_frame(WSType.RESULT)
class ResultFrame(WSBase):
    """Home Assistant result frame."""

    type: WSType = WSType.RESULT
    success: bool
    result: Any | None = None
    error: WSError | None = None


@register_frame(WSType.SUBSCRIBE_EVENTS)
class SubscribeEventsFrame(WSBase):
    """Home Assistant subscribe events frame."""

    type: WSType = WSType.SUBSCRIBE_EVENTS
    event_type: str | None = None


class HAWSContext(BaseModel):
    """Context object embedded in an event frame."""

    model_config = ConfigDict(extra="ignore")

    id: str
    parent_id: str | None = None
    user_id: str | None = None


class HAEvent(BaseModel):
    """Event object embedded in an event frame."""

    model_config = ConfigDict(extra="ignore")

    event_type: str
    time_fired: str | None = None
    origin: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    context: HAWSContext | None = None


@register_frame(WSType.EVENT)
class EventFrame(WSBase):
    """Home Assistant event frame."""

    type: WSType = WSType.EVENT
    event: HAEvent


def parse_incoming(payload: dict[str, Any]) -> WSBase:
    """Parse an incoming WS message dict into a concrete frame model."""
    base = IncomingFrame.model_validate(payload)
    model = FRAME_REGISTRY.get(base.type)
    if model is None:
        raise ValueError(f"Unsupported WS frame type: {base.type!r}")
    return model.model_validate(payload)
