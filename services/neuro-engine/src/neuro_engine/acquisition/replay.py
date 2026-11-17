"""Play a recording.v1 file through the same adapter interface as live EEG."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np

from neuro_engine.acquisition.base import SampleBlock, StreamDescriptor
from neuro_engine.acquisition.clock import Clock
from neuro_engine.recordings.v1 import (
    Recording,
    RecordingError,
    cursor_at,
    present_runs,
)


class ReplayEegAdapter:
    """Single-use DeviceAdapter. Seek is a new instance, opened by the session."""

    def __init__(
        self,
        recording: Recording,
        clock: Clock,
        *,
        start_index: int = 0,
        block_size: int = 25,
        pause: asyncio.Event | None = None,
    ) -> None:
        if block_size < 1:
            raise RecordingError("invalid-block", "block_size must be positive")
        self._recording = recording
        self._clock = clock
        self._start_index = start_index
        self._block_size = block_size
        self._pause = pause or asyncio.Event()
        if pause is None:
            self._pause.set()
        self._opened = False
        self._closed = False
        self._descriptor = recording.descriptor

    async def open(self) -> StreamDescriptor:
        if self._opened or self._closed:
            raise RuntimeError("ReplayEegAdapter is single-use")
        self._opened = True
        return self._descriptor

    async def blocks(self) -> AsyncIterator[SampleBlock]:
        if not self._opened:
            raise RuntimeError("open() must be called before blocks()")
        cursor = cursor_at(self._recording, self._start_index)
        if cursor is None:
            return
        sample_index, stored = cursor
        origin = sample_index
        opened_us = self._clock.monotonic_us()
        held_us = 0
        rate = self._descriptor.nominal_sample_rate_hz
        period_us = 1_000_000 / rate
        runs = present_runs(self._recording.sample_count, self._recording.gaps)
        for run_index, run_stored, length in runs:
            run_end_stored = run_stored + length
            if stored >= run_end_stored:
                continue
            stored = max(stored, run_stored)
            # Recompute on every run. A gap ends one run on the next run's stored
            # offset, so `stored < run_stored` is false and must not keep the
            # pre-gap index.
            sample_index = run_index + (stored - run_stored)
            while stored < run_end_stored:
                if not self._pause.is_set():
                    paused_at = self._clock.monotonic_us()
                    await self._pause.wait()
                    held_us += self._clock.monotonic_us() - paused_at
                if self._closed:
                    return
                take = min(self._block_size, run_end_stored - stored)
                data = np.ascontiguousarray(self._recording.samples[:, stored : stored + take])
                await self._clock.sleep_until(
                    opened_us + held_us + round((sample_index - origin + take) * period_us)
                )
                if self._closed:
                    return
                yield SampleBlock(
                    first_sample_index=sample_index,
                    first_sample_time_us=opened_us + held_us + round((sample_index - origin) * period_us),
                    data=data,
                )
                stored += take
                sample_index += take

    async def close(self) -> None:
        self._closed = True
        self._pause.set()
