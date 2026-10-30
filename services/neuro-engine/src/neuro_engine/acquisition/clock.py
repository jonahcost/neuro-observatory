"""Engine timebase. All acquisition times are engine-monotonic microseconds."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic_us(self) -> int: ...

    def unix_time_us(self) -> int: ...

    async def sleep_until(self, deadline_us: int) -> None: ...


class MonotonicClock:
    """Real host clock. Monotonic time is immune to wall-clock adjustments."""

    def monotonic_us(self) -> int:
        return time.monotonic_ns() // 1000

    def unix_time_us(self) -> int:
        return time.time_ns() // 1000

    async def sleep_until(self, deadline_us: int) -> None:
        delay_s = (deadline_us - self.monotonic_us()) / 1_000_000
        await asyncio.sleep(max(0.0, delay_s))


class VirtualClock:
    """Deterministic clock for tests and offline generation.

    Sleeping advances virtual time to the deadline immediately (yielding once
    to the event loop), so paced sources run as fast as consumers allow.
    """

    def __init__(self, start_us: int = 1_000_000, unix_offset_us: int = 1_793_366_580_000_000) -> None:
        self._now_us = start_us
        self._unix_offset_us = unix_offset_us

    def monotonic_us(self) -> int:
        return self._now_us

    def unix_time_us(self) -> int:
        return self._unix_offset_us + self._now_us

    def advance(self, delta_us: int) -> None:
        if delta_us < 0:
            raise ValueError("virtual time cannot go backwards")
        self._now_us += delta_us

    async def sleep_until(self, deadline_us: int) -> None:
        self._now_us = max(self._now_us, deadline_us)
        await asyncio.sleep(0)
