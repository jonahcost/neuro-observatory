"""Acquisition lifecycle, independent of any consumer or client connection."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import numpy as np

from neuro_engine.acquisition.base import (
    MAX_BLOCK_SAMPLES,
    MAX_SAFE_INTEGER,
    AcquisitionError,
    ActiveStream,
    DeviceAdapter,
    SampleBlock,
    StreamBlock,
)
from neuro_engine.acquisition.clock import Clock
from neuro_engine.streaming.hub import StreamClosed, StreamHub, StreamOpened

logger = logging.getLogger(__name__)

MIN_RATE_WINDOW_US = 1_000_000
MIN_STALE_WINDOW_US = 1_000_000
STALE_WINDOW_BLOCKS = 3

HealthReason = Literal["not-streaming", "no-recent-data", "recent-rejections"]


class AcquisitionState(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    initial_delay_s: float = 0.5
    max_delay_s: float = 10.0
    max_attempts: int | None = None
    """Consecutive failed attempts before giving up; None retries forever."""

    def delay_s(self, attempt: int) -> float:
        return min(self.max_delay_s, self.initial_delay_s * 2 ** max(0, attempt - 1))


@dataclass(frozen=True, slots=True)
class AcquisitionErrorInfo:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AcquisitionStatus:
    state: AcquisitionState
    stream_id: str | None
    at_us: int
    samples_acquired: int
    acquisition_gap_samples: int
    rejected_blocks: int
    effective_sample_rate_hz: float | None
    error: AcquisitionErrorInfo | None


@dataclass(frozen=True, slots=True)
class AcquisitionHealth:
    """Whether data is actually flowing; `reasons` is empty when healthy."""

    reasons: tuple[HealthReason, ...]

    @property
    def ok(self) -> bool:
        return not self.reasons


class AcquisitionService:
    """Runs one adapter at a time and publishes accepted blocks to the hub.

    Responsibilities: state machine, stream IDs, block sequence numbers,
    acquisition-gap derivation from device sample indices, rejection of
    malformed/duplicate/overlapping/out-of-range blocks, splitting of blocks
    larger than the protocol allows, reconnection with capped backoff.
    Each (re)connection opens a new stream; continuity is never assumed.
    """

    def __init__(
        self,
        adapter_factory: Callable[[], DeviceAdapter],
        hub: StreamHub,
        clock: Clock,
        *,
        reconnect: ReconnectPolicy | None = None,
        stream_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._hub = hub
        self._clock = clock
        self._reconnect = reconnect or ReconnectPolicy()
        self._new_stream_id = stream_id_factory or (lambda: uuid.uuid4().hex)
        self._task: asyncio.Task[None] | None = None
        self._state = AcquisitionState.IDLE
        self._error: AcquisitionErrorInfo | None = None
        self._stream: ActiveStream | None = None
        self._session_delivered = False
        self._reset_counters()

    def _reset_counters(self) -> None:
        self._next_index = 0
        self._next_sequence = 0
        self._samples_acquired = 0
        self._gap_samples = 0
        self._rejected_blocks = 0
        self._first_block_at_us: int | None = None
        self._first_block_end_index = 0
        self._last_block_at_us: int | None = None
        self._last_block_duration_us = 0.0
        self._last_rejected_at_us: int | None = None

    @property
    def state(self) -> AcquisitionState:
        return self._state

    @property
    def current_stream(self) -> ActiveStream | None:
        return self._stream

    def status(self) -> AcquisitionStatus:
        stream = self._stream
        rate: float | None = None
        if self._first_block_at_us is not None and self._last_block_at_us is not None:
            span_us = self._last_block_at_us - self._first_block_at_us
            if span_us >= MIN_RATE_WINDOW_US:
                rate = (self._next_index - self._first_block_end_index) * 1_000_000 / span_us
        return AcquisitionStatus(
            state=self._state,
            stream_id=stream.stream_id if stream else None,
            at_us=self._clock.monotonic_us(),
            samples_acquired=self._samples_acquired,
            acquisition_gap_samples=self._gap_samples,
            rejected_blocks=self._rejected_blocks,
            effective_sample_rate_hz=rate,
            error=self._error,
        )

    def health(self) -> AcquisitionHealth:
        """Degraded unless streaming with a recently accepted block and no recent rejections.

        The stale window is STALE_WINDOW_BLOCKS durations of the last accepted
        block, at least MIN_STALE_WINDOW_US; before the first block it is
        measured from stream open.
        """
        reasons: list[HealthReason] = []
        if self._state is not AcquisitionState.STREAMING:
            reasons.append("not-streaming")
        stream = self._stream
        if stream is not None:
            now_us = self._clock.monotonic_us()
            window_us = max(MIN_STALE_WINDOW_US, STALE_WINDOW_BLOCKS * self._last_block_duration_us)
            last_progress_us = self._last_block_at_us if self._last_block_at_us is not None else stream.anchor_monotonic_us
            if now_us - last_progress_us > window_us:
                reasons.append("no-recent-data")
            if self._last_rejected_at_us is not None and now_us - self._last_rejected_at_us <= window_us:
                reasons.append("recent-rejections")
        return AcquisitionHealth(tuple(reasons))

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="acquisition-service")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._state is not AcquisitionState.FAILED:
            self._state = AcquisitionState.STOPPED

    async def wait(self) -> None:
        """Wait until the run loop ends on its own (failed or source exhausted)."""
        if self._task is not None:
            await asyncio.shield(self._task)

    async def _run(self) -> None:
        attempt = 0
        while True:
            self._state = AcquisitionState.CONNECTING if attempt == 0 else AcquisitionState.RECONNECTING
            self._session_delivered = False
            try:
                await self._run_stream(self._adapter_factory())
            except AcquisitionError as exc:
                self._error = AcquisitionErrorInfo(code=exc.code, message=str(exc) or exc.code)
                logger.warning("Acquisition error %s (retryable=%s)", exc.code, exc.retryable)
                if not exc.retryable:
                    self._state = AcquisitionState.FAILED
                    return
            except Exception:
                logger.exception("Unexpected acquisition failure")
                self._error = AcquisitionErrorInfo(code="internal-error", message="unexpected acquisition failure")
                self._state = AcquisitionState.FAILED
                return
            else:
                self._state = AcquisitionState.STOPPED
                return
            attempt = 1 if self._session_delivered else attempt + 1
            if self._reconnect.max_attempts is not None and attempt > self._reconnect.max_attempts:
                self._state = AcquisitionState.FAILED
                return
            self._state = AcquisitionState.RECONNECTING
            delay_us = round(self._reconnect.delay_s(attempt) * 1_000_000)
            await self._clock.sleep_until(self._clock.monotonic_us() + delay_us)

    async def _run_stream(self, adapter: DeviceAdapter) -> None:
        """Run one adapter session until the source ends or raises."""
        try:
            descriptor = await adapter.open()
            stream = ActiveStream(
                stream_id=self._new_stream_id(),
                descriptor=descriptor,
                anchor_monotonic_us=self._clock.monotonic_us(),
                anchor_unix_time_us=self._clock.unix_time_us(),
            )
            self._reset_counters()
            self._stream = stream
            self._state = AcquisitionState.STREAMING
            self._hub.publish(StreamOpened(stream))
            async for block in adapter.blocks():
                self._accept(stream, block)
        finally:
            try:
                await adapter.close()
            except Exception:
                logger.exception("Adapter close() failed; the session outcome is unchanged")
            finally:
                if self._stream is not None:
                    self._hub.publish(StreamClosed(self._stream.stream_id))
                    self._stream = None

    def _accept(self, stream: ActiveStream, block: SampleBlock) -> None:
        if block.channel_count != stream.descriptor.channel_count:
            self._reject("channel count does not match the stream descriptor")
            return
        if not np.isfinite(block.data).all():
            self._reject("non-finite sample values")
            return
        if block.first_sample_index < self._next_index:
            self._reject("duplicate or out-of-order sample index")
            return
        period_us = 1_000_000 / stream.descriptor.nominal_sample_rate_hz
        end_index = block.first_sample_index + block.sample_count
        last_time_us = block.first_sample_time_us + round((block.sample_count - 1) * period_us)
        if end_index > MAX_SAFE_INTEGER or block.first_sample_time_us < 0 or last_time_us > MAX_SAFE_INTEGER:
            self._reject("sample index or timestamp outside the protocol range")
            return
        dropped = block.first_sample_index - self._next_index
        for offset in range(0, block.sample_count, MAX_BLOCK_SAMPLES):
            self._hub.publish(
                StreamBlock(
                    stream_id=stream.stream_id,
                    block_sequence=self._next_sequence,
                    dropped_samples_before=dropped if offset == 0 else 0,
                    block=_block_part(block, offset, period_us),
                )
            )
            self._next_sequence += 1
        now_us = self._clock.monotonic_us()
        if self._first_block_at_us is None:
            self._first_block_at_us = now_us
            self._first_block_end_index = end_index
        self._next_index = end_index
        self._samples_acquired += block.sample_count
        self._gap_samples += dropped
        self._last_block_at_us = now_us
        self._last_block_duration_us = block.sample_count * period_us
        self._session_delivered = True
        self._error = None

    def _reject(self, reason: str) -> None:
        self._rejected_blocks += 1
        self._last_rejected_at_us = self._clock.monotonic_us()
        logger.warning("Rejected device block: %s", reason)


def _block_part(block: SampleBlock, offset: int, period_us: float) -> SampleBlock:
    """Samples [offset, offset + MAX_BLOCK_SAMPLES) of `block`, timed by the protocol's sample-time rule."""
    if offset == 0 and block.sample_count <= MAX_BLOCK_SAMPLES:
        return block
    stop = offset + MAX_BLOCK_SAMPLES
    stamps = block.device_timestamps_us
    return SampleBlock(
        first_sample_index=block.first_sample_index + offset,
        first_sample_time_us=block.first_sample_time_us + round(offset * period_us),
        data=block.data[:, offset:stop],
        device_timestamps_us=stamps[offset:stop] if stamps is not None else None,
    )
