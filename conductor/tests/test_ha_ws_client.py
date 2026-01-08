"""Test for the HA WebSocket client."""
# pylint: disable=protected-access, too-few-public-methods, redefined-builtin

import asyncio
import json
import logging
import typing
from abc import abstractmethod
from typing import Any, Protocol, cast
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from conductor.ha_websocket import (
    HA_WS_CLIENT_NAME,
    HAWebSocketAuthError,
    HAWebSocketClient,
    HAWebSocketError,
)
from conductor.models.ha_ws import (
    AuthFrame,
    AuthInvalid,
    AuthOk,
    AuthRequired,
    WSType,
    parse_incoming,
)

from . import load_fixtures


class _SupportsSetWSMessages(Protocol):
    """Protocol to allow setting websocket messages for testing."""

    @abstractmethod
    def set_ws_messages(self, messages: list[Any]) -> None:
        """Preset websocket messages to be yielded by the client stub."""


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
    started = asyncio.Event()
    gatekeeper = asyncio.Event()

    async def dummy_task() -> None:
        """Dummy task to simulate running client."""
        started.set()
        await gatekeeper.wait()  # Just need to wait, so we can test

    with patch.object(client_init, "_run", new=dummy_task):
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


async def test_client_authentication_unexpected_first_frame(client_init: HAWebSocketClient) -> None:
    """Test if the first frame isn't auth_required. Don't know why, but let's be thorough."""
    with (
        patch.object(
            client_init,
            "_receive_message",
            new=AsyncMock(return_value=AuthOk(type=WSType.AUTH_OK)),
        ),
        patch.object(
            client_init,
            "_send_message",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(HAWebSocketAuthError, match="Unexpected response from Home Assistant"):
            await client_init.authenticate()


async def test_client_authentication_success_branch(
    client_init: HAWebSocketClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A valid authentication.."""
    caplog.set_level(logging.INFO, logger="conductor.ha_websocket")

    with (
        patch.object(client_init, "_send_message", new=AsyncMock()) as send_mock,
        patch.object(
            client_init,
            "_receive_message",
            new=AsyncMock(
                side_effect=[
                    AuthRequired(type=WSType.AUTH_REQUIRED, ha_version="2026.1.0"),
                    AuthOk(type=WSType.AUTH_OK, ha_version="2026.1.0"),
                ]
            ),
        ) as recv_mock,
    ):
        await client_init.authenticate()

        send_mock.assert_awaited_once()
        assert recv_mock.await_count == 2
        assert "Successfully authenticated to Home Assistant Websocket" in caplog.text


async def test_client_authentication_invalid_token(client_init: HAWebSocketClient) -> None:
    """Test invalid token."""
    client_init.config.token = "invalid_token"

    with (
        patch.object(client_init, "_send_message", new=AsyncMock()) as send_mock,
        patch.object(
            client_init,
            "_receive_message",
            new=AsyncMock(
                side_effect=[
                    AuthRequired(type=WSType.AUTH_REQUIRED, ha_version="2026.1.0"),
                    AuthInvalid(type=WSType.AUTH_INVALID, message="Invalid password"),
                ]
            ),
        ) as recv_mock,
    ):
        with pytest.raises(HAWebSocketAuthError, match="Invalid password"):
            await client_init.authenticate()

        send_mock.assert_awaited_once()
        sent_payload = send_mock.call_args.args[0]
        assert isinstance(sent_payload, AuthFrame)
        assert sent_payload.type == WSType.AUTH
        assert sent_payload.access_token == "invalid_token"
        assert recv_mock.await_count == 2


async def test_client_connect_and_listen(client: HAWebSocketClient) -> None:
    """Test connecting and listening with the HA Websocket client using mocks."""
    # Attach an empty websocket iterator so the loop exits immediately
    cast(_SupportsSetWSMessages, client).set_ws_messages([])

    await client._connect_and_listen()


async def test_client_connect_and_listen_error(client: HAWebSocketClient) -> None:
    """Test exception handling in the _run method of the HA Websocket client."""

    class Msg:
        """Mock message class."""

        def __init__(self, type) -> None:
            self.type = type

    cast(_SupportsSetWSMessages, client).set_ws_messages([Msg(aiohttp.WSMsgType.ERROR)])
    assert client._ws is not None
    with patch.object(client._ws, "exception", return_value=Exception("Test exception")):
        with pytest.raises(HAWebSocketError, match="Websocket error"):
            await client._connect_and_listen()


async def test_client_connect_and_listen_closed_client(client: HAWebSocketClient) -> None:
    """Test handling of closed websocket in the _run method of the HA Websocket client."""

    class Msg:
        """ "Mock message class."""

        def __init__(self, type) -> None:
            self.type = type

    cast(_SupportsSetWSMessages, client).set_ws_messages([Msg(aiohttp.WSMsgType.CLOSED)])

    with pytest.raises(HAWebSocketError, match="Websocket closed"):
        await client._connect_and_listen()


async def test_client_subscribe_events(client_init: HAWebSocketClient) -> None:
    """Test subscribing to events."""
    client_init._msg_id = 0

    with (
        patch.object(client_init, "_send_message", new=AsyncMock()) as send_mock,
        patch.object(
            client_init,
            "_receive_message",
            new=AsyncMock(
                return_value=parse_incoming(json.loads(load_fixtures("result_frame.json")))
            ),
        ),
    ):
        sub_id = await client_init._subscribe_events()

    send_mock.assert_awaited_once()
    assert sub_id == 1


async def test_client_handle_message(
    client: HAWebSocketClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test handling of incoming messages and log warnings."""
    caplog.set_level(logging.WARNING, logger="conductor.ha_websocket")

    success_payload = json.loads(load_fixtures("ha_event.json"))
    result_ok = parse_incoming(success_payload)
    await client._handle_message(result_ok)

    # Test failure handling, right away :)
    failure_payload = json.loads(load_fixtures("result_frame_failure.json"))
    result_fail = parse_incoming(failure_payload)
    await client._handle_message(result_fail)


async def test_run_handles_timeout_backoff(
    client: HAWebSocketClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_run should log timeout and schedule reconnect with backoff."""
    caplog.set_level(logging.WARNING, logger="conductor.ha_websocket")
    caplog.set_level(logging.INFO, logger="conductor.ha_websocket")

    async def sleep_side_effect(_):
        client._stop.set()  # Stop after first backoff

    sleep_mock = AsyncMock(side_effect=sleep_side_effect)
    monkeypatch.setattr("conductor.ha_websocket.asyncio.sleep", sleep_mock)

    with patch.object(
        client,
        "_connect_and_listen",
        new=AsyncMock(side_effect=asyncio.TimeoutError()),
    ):
        await client._run()

    assert any("Connection timed out" in rec.message for rec in caplog.records)
    assert any("Reconnecting in" in rec.message for rec in caplog.records)
    sleep_mock.assert_awaited_once()


async def test_run_handles_cancelled(
    client: HAWebSocketClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_run should warn on cancellation and attempt reconnect."""
    caplog.set_level(logging.WARNING, logger="conductor.ha_websocket")
    caplog.set_level(logging.INFO, logger="conductor.ha_websocket")

    with patch.object(
        client,
        "_connect_and_listen",
        new=AsyncMock(side_effect=asyncio.CancelledError("boom")),
    ):

        async def sleep_side_effect(_):
            client._stop.set()

        sleep_mock = AsyncMock(side_effect=sleep_side_effect)
        monkeypatch.setattr("conductor.ha_websocket.asyncio.sleep", sleep_mock)

        await client._run()

        assert any("task was cancelled" in rec.message for rec in caplog.records)
        assert any("Reconnecting in" in rec.message for rec in caplog.records)
        sleep_mock.assert_awaited_once()


async def test_run_handles_ws_error(
    client: HAWebSocketClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_run should log HAWebSocketError and attempt reconnect."""
    caplog.set_level(logging.ERROR, logger="conductor.ha_websocket")
    caplog.set_level(logging.INFO, logger="conductor.ha_websocket")

    with patch.object(
        client,
        "_connect_and_listen",
        new=AsyncMock(side_effect=HAWebSocketError("boom")),
    ):

        async def sleep_side_effect(_):
            client._stop.set()

        sleep_mock = AsyncMock(side_effect=sleep_side_effect)
        monkeypatch.setattr("conductor.ha_websocket.asyncio.sleep", sleep_mock)

        await client._run()

        assert any("Websocket error:" in rec.message for rec in caplog.records)
        assert any("Reconnecting in" in rec.message for rec in caplog.records)
        sleep_mock.assert_awaited_once()


async def test_run_handles_unexpected_exception(
    client: HAWebSocketClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_run should log unexpected exceptions and attempt reconnect."""
    caplog.set_level(logging.ERROR, logger="conductor.ha_websocket")
    caplog.set_level(logging.INFO, logger="conductor.ha_websocket")

    with patch.object(
        client,
        "_connect_and_listen",
        new=AsyncMock(side_effect=Exception("boom")),
    ):

        async def sleep_side_effect(_):
            client._stop.set()

        sleep_mock = AsyncMock(side_effect=sleep_side_effect)
        monkeypatch.setattr("conductor.ha_websocket.asyncio.sleep", sleep_mock)

        await client._run()

        assert any("Unexpected websocket failure:" in rec.message for rec in caplog.records)
        assert any("Reconnecting in" in rec.message for rec in caplog.records)
        sleep_mock.assert_awaited_once()


async def test_run_success_reconnects_then_stops(
    client: HAWebSocketClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On success, _run resets backoff and schedules reconnect; then we stop. Tada!"""
    caplog.set_level(logging.INFO, logger="conductor.ha_websocket")

    with patch.object(
        client,
        "_connect_and_listen",
        new=AsyncMock(return_value=None),
    ):

        async def sleep_side_effect(_):
            client._stop.set()

        sleep_mock = AsyncMock(side_effect=sleep_side_effect)
        monkeypatch.setattr("conductor.ha_websocket.asyncio.sleep", sleep_mock)

        await client._run()

        assert any("Reconnecting in" in rec.message for rec in caplog.records)
        sleep_mock.assert_awaited_once()


async def test_client_receive_message(client_init: HAWebSocketClient) -> None:
    """Test receiving and parsing a message from the websocket."""
    sample_payload = json.loads(load_fixtures("ha_event.json"))
    raw_message = aiohttp.WSMessage(
        type=aiohttp.WSMsgType.TEXT,
        data=json.dumps(sample_payload),
        extra=None,
    )

    class _WS:
        closed = False

        async def receive(self) -> Any:
            """Return the preset text message."""
            return raw_message

        async def close(self) -> None:
            """Close it."""
            self.closed = True

        def exception(self) -> Exception:
            """Return an exception."""
            return Exception("unused")

    client_init._ws = typing.cast(aiohttp.ClientWebSocketResponse, _WS())
    message = await client_init._receive_message()

    assert message.type == WSType.EVENT
    assert hasattr(message, "event")


async def test_client_receive_message_error(client_init: HAWebSocketClient) -> None:
    """Test receiving a non-text message raises an error."""
    raw_message = aiohttp.WSMessage(
        type=aiohttp.WSMsgType.ERROR,
        data=None,
        extra=None,
    )

    class _WS:
        closed = False

        async def receive(self) -> Any:
            """Return the preset error message.""" ""
            return raw_message

        async def close(self) -> None:
            """Close it.""" ""
            self.closed = True

        def exception(self) -> Exception:
            """Return an exception."""
            return Exception("Test exception")

    client_init._ws = typing.cast(aiohttp.ClientWebSocketResponse, _WS())
    with pytest.raises(HAWebSocketError, match="Websocket error"):
        await client_init._receive_message()


async def test_client_receive_message_closed(client_init: HAWebSocketClient) -> None:
    """Test receiving a closed message raises an error."""
    raw_message = aiohttp.WSMessage(
        type=aiohttp.WSMsgType.CLOSED,
        data=None,
        extra=None,
    )

    class _WS:
        closed = False

        async def receive(self) -> Any:
            """Return the preset closed message."""
            return raw_message

        async def close(self) -> None:
            """Close it."""
            self.closed = True

        def exception(self) -> Exception:
            """Return an exception."""
            return Exception("unused")

    client_init._ws = typing.cast(aiohttp.ClientWebSocketResponse, _WS())
    with pytest.raises(HAWebSocketError, match="Websocket closed"):
        await client_init._receive_message()
