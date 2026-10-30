"""Protocol v2 WebSocket endpoint: a live-view consumer of the stream hub."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from neuro_engine.acquisition.base import ActiveStream, StreamBlock
from neuro_engine.protocol import v2
from neuro_engine.protocol.convert import (
    block_message,
    metadata_message,
    status_message,
)
from neuro_engine.streaming.hub import (
    DeliveryPolicy,
    StreamClosed,
    StreamOpened,
    Subscription,
    SubscriptionClosed,
)

if TYPE_CHECKING:
    from neuro_engine.app import EngineRuntime

logger = logging.getLogger(__name__)
router = APIRouter()

CLOSE_UNSUPPORTED_DATA = 1003
CLOSE_POLICY_VIOLATION = 1008
CLOSE_INTERNAL_ERROR = 1011
CLOSE_TRY_AGAIN_LATER = 1013


@router.websocket("/ws/v2/eeg")
async def eeg_stream(websocket: WebSocket) -> None:
    runtime: EngineRuntime = websocket.app.state.engine
    origin = websocket.headers.get("origin")
    # Browsers always send Origin; refusing unknown origins prevents other web
    # pages from reading the local stream. Non-browser local clients omit it.
    if origin is not None and origin not in runtime.settings.allowed_origins:
        logger.warning("Rejected EEG WebSocket from a disallowed origin")
        await websocket.close(code=CLOSE_POLICY_VIOLATION)
        return
    await websocket.accept()
    # Subscribing and reading the current stream must happen without an await in
    # between, so every queued event is newer than the metadata sent first.
    subscription = runtime.hub.subscribe(
        "websocket", DeliveryPolicy.LIVE_VIEW, runtime.settings.live_view_queue_blocks
    )
    current = runtime.service.current_stream
    close_code: int | None = None
    try:
        async with asyncio.TaskGroup() as session:
            session.create_task(_send_stream(websocket, runtime, subscription, current))
            session.create_task(_receive_until_closed(websocket))
    except* _SessionEnded as ended:
        close_code = next(e.close_code for e in ended.exceptions if isinstance(e, _SessionEnded))
    finally:
        runtime.hub.unsubscribe(subscription)
    if close_code is not None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=close_code)


class _SessionEnded(Exception):
    """Ends both session tasks; `close_code` is None when the client already left."""

    def __init__(self, close_code: int | None) -> None:
        super().__init__(close_code)
        self.close_code = close_code


async def _receive_until_closed(websocket: WebSocket) -> None:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise _SessionEnded(None)
    # Protocol v2 defines no client-to-server messages.
    raise _SessionEnded(CLOSE_UNSUPPORTED_DATA)


async def _send_stream(
    websocket: WebSocket, runtime: EngineRuntime, subscription: Subscription, current: ActiveStream | None
) -> None:
    try:
        await _forward_events(websocket, runtime, subscription, current)
    except SubscriptionClosed:
        raise _SessionEnded(CLOSE_TRY_AGAIN_LATER) from None
    except (v2.ProtocolError, ValidationError):
        logger.exception("Could not encode a protocol v2 message; closing the session")
        raise _SessionEnded(CLOSE_INTERNAL_ERROR) from None
    except (WebSocketDisconnect, OSError):
        raise _SessionEnded(None) from None
    except RuntimeError:
        # Starlette raises RuntimeError when sending on a socket that is already closed.
        if WebSocketState.DISCONNECTED in (websocket.client_state, websocket.application_state):
            raise _SessionEnded(None) from None
        raise


async def _forward_events(
    websocket: WebSocket, runtime: EngineRuntime, subscription: Subscription, current: ActiveStream | None
) -> None:
    service = runtime.service
    interval = runtime.settings.status_interval_s
    loop = asyncio.get_running_loop()
    metadata: v2.StreamMetadata | None = None

    async def send_status() -> None:
        await websocket.send_text(v2.encode(status_message(service.status(), subscription.dropped_blocks)))

    if current is not None:
        metadata = metadata_message(current)
        await websocket.send_text(v2.encode(metadata))
    await send_status()
    next_status_at = loop.time() + interval
    while True:
        event = await subscription.get(timeout=max(0.0, next_status_at - loop.time()))
        if isinstance(event, StreamOpened):
            metadata = metadata_message(event.stream)
            await websocket.send_text(v2.encode(metadata))
        elif isinstance(event, StreamBlock):
            await websocket.send_text(v2.encode(block_message(event), metadata))
        elif isinstance(event, StreamClosed):
            metadata = None
            await send_status()
        if loop.time() >= next_status_at:
            await send_status()
            next_status_at = loop.time() + interval
