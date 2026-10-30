from __future__ import annotations

import asyncio

from neuro_engine.acquisition.clock import MonotonicClock, VirtualClock
from neuro_engine.acquisition.synthetic import SyntheticConfig, SyntheticEegAdapter


def test_virtual_clock_pacing_has_no_cumulative_drift_over_10000_blocks() -> None:
    clock = VirtualClock()
    adapter = SyntheticEegAdapter(SyntheticConfig(block_size=25), clock)

    async def scenario() -> tuple[int, int, int]:
        await adapter.open()
        start = clock.monotonic_us()
        count = 0
        last_index = 0
        async for block in adapter.blocks():
            count += 1
            last_index = block.first_sample_index + block.sample_count
            if count == 10_000:
                break
        await adapter.close()
        return start, clock.monotonic_us(), last_index

    start, end, samples = asyncio.run(scenario())
    assert samples == 250_000
    # 250 000 samples at 125 Hz = exactly 2000 s; the release deadline equals the last sample's end.
    assert end - start == 2_000_000_000


def test_virtual_clock_rejects_negative_advance() -> None:
    clock = VirtualClock(start_us=10)
    clock.advance(5)
    assert clock.monotonic_us() == 15
    try:
        clock.advance(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_real_time_effective_rate_within_two_percent() -> None:
    clock = MonotonicClock()
    adapter = SyntheticEegAdapter(SyntheticConfig(block_size=5), clock)

    async def scenario() -> tuple[int, int]:
        await adapter.open()
        start = clock.monotonic_us()
        samples = 0
        async for block in adapter.blocks():
            samples += block.sample_count
            if samples >= 150:  # 1.2 s at 125 Hz
                break
        elapsed = clock.monotonic_us() - start
        await adapter.close()
        return samples, elapsed

    samples, elapsed_us = asyncio.run(scenario())
    rate = samples * 1_000_000 / elapsed_us
    assert abs(rate - 125.0) / 125.0 < 0.02
