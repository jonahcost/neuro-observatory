from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from neuro_engine.acquisition.base import (
    DeviceConfigError,
    DeviceConnectionError,
    SampleBlock,
    StreamBlock,
    StreamDescriptor,
)
from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.service import (
    AcquisitionService,
    AcquisitionState,
    ReconnectPolicy,
)
from neuro_engine.acquisition.synthetic import (
    SyntheticConfig,
    SyntheticEegAdapter,
    SyntheticFault,
)
from neuro_engine.streaming.hub import (
    DeliveryPolicy,
    StreamClosed,
    StreamEvent,
    StreamHub,
    StreamOpened,
)

FAST_RECONNECT = ReconnectPolicy(initial_delay_s=0.1, max_delay_s=1.0, max_attempts=3)


def sequential_ids() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"stream-{next(counter)}"


class ScriptedAdapter:
    """Adapter delivering a fixed list of blocks, then ending the stream."""

    def __init__(self, descriptor: StreamDescriptor, blocks: list[SampleBlock], open_error: Exception | None = None):
        self.descriptor = descriptor
        self._blocks = blocks
        self._open_error = open_error
        self.closed = False

    async def open(self) -> StreamDescriptor:
        if self._open_error is not None:
            raise self._open_error
        return self.descriptor

    async def blocks(self) -> AsyncIterator[SampleBlock]:
        for block in self._blocks:
            await asyncio.sleep(0)
            yield block

    async def close(self) -> None:
        self.closed = True


def block(index: int, n: int = 5, channels: int = 16, value: float = 1.0) -> SampleBlock:
    return SampleBlock(index, index * 8_000, np.full((channels, n), value))


async def drain(hub_events: list[StreamEvent], sub, until: Callable[[list[StreamEvent]], bool]) -> None:
    while not until(hub_events):
        event = await asyncio.wait_for(sub.get(), 5)
        if event is not None:
            hub_events.append(event)


def test_streams_blocks_with_sequence_gaps_and_status() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    service = AcquisitionService(
        lambda: SyntheticEegAdapter(SyntheticConfig(block_size=25), clock),
        hub,
        clock,
        stream_id_factory=sequential_ids(),
    )

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) for e in ev) >= 10)
        status = service.status()
        await service.stop()
        assert isinstance(events[0], StreamOpened)
        assert events[0].stream.stream_id == "stream-1"
        blocks = [e for e in events if isinstance(e, StreamBlock)]
        assert [b.block_sequence for b in blocks[:10]] == list(range(10))
        assert [b.block.first_sample_index for b in blocks[:10]] == [n * 25 for n in range(10)]
        assert all(b.dropped_samples_before == 0 for b in blocks)
        assert status.state is AcquisitionState.STREAMING
        assert status.stream_id == "stream-1"
        assert status.samples_acquired >= 250
        assert status.effective_sample_rate_hz == pytest.approx(125.0)
        assert service.state is AcquisitionState.STOPPED
        assert service.current_stream is None

    asyncio.run(scenario())


def test_device_gap_becomes_dropped_samples_before() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    service = AcquisitionService(
        lambda: SyntheticEegAdapter(SyntheticConfig(block_size=10), clock, faults=[SyntheticFault("drop", 15, 7)]),
        hub,
        clock,
    )

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) for e in ev) >= 4)
        await service.stop()
        blocks = [e for e in events if isinstance(e, StreamBlock)]
        assert [(b.block.first_sample_index, b.dropped_samples_before) for b in blocks[:4]] == [
            (0, 0),
            (10, 0),
            (22, 7),
            (30, 0),
        ]
        assert [b.block_sequence for b in blocks[:4]] == [0, 1, 2, 3]
        assert service.status().acquisition_gap_samples == 7

    asyncio.run(scenario())


def test_disconnect_reconnects_with_a_new_stream_and_closes_adapters() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapters: list[SyntheticEegAdapter] = []

    def factory() -> SyntheticEegAdapter:
        faults = [SyntheticFault("disconnect", at_sample=50)] if not adapters else []
        adapters.append(SyntheticEegAdapter(SyntheticConfig(block_size=25), clock, faults=faults))
        return adapters[-1]

    service = AcquisitionService(factory, hub, clock, reconnect=FAST_RECONNECT, stream_id_factory=sequential_ids())

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamOpened) for e in ev) >= 2)
        await drain(events, sub, lambda ev: isinstance(ev[-1], StreamBlock) and ev[-1].stream_id == "stream-2")
        await service.stop()
        kinds = [type(e).__name__ for e in events]
        assert kinds[:4] == ["StreamOpened", "StreamBlock", "StreamBlock", "StreamClosed"]
        assert isinstance(events[4], StreamOpened) and events[4].stream.stream_id == "stream-2"
        second = events[5]
        assert isinstance(second, StreamBlock)
        assert (second.block_sequence, second.block.first_sample_index, second.dropped_samples_before) == (0, 0, 0)
        assert adapters[0].closed and adapters[1].closed
        assert service.status().error is None  # cleared once streaming resumed

    asyncio.run(scenario())


def test_invalid_device_configuration_fails_without_retry() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    calls = 0

    def factory() -> ScriptedAdapter:
        nonlocal calls
        calls += 1
        return ScriptedAdapter(SyntheticConfig().descriptor(), [], open_error=DeviceConfigError("bad gain"))

    service = AcquisitionService(factory, hub, clock, reconnect=FAST_RECONNECT)

    async def scenario() -> None:
        await service.start()
        await asyncio.wait_for(service.wait(), 5)

    asyncio.run(scenario())
    status = service.status()
    assert calls == 1
    assert status.state is AcquisitionState.FAILED
    assert status.error is not None and status.error.code == "invalid-device-config"


def test_connection_failures_back_off_and_give_up_after_max_attempts() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    opens: list[int] = []

    def factory() -> ScriptedAdapter:
        opens.append(clock.monotonic_us())
        return ScriptedAdapter(SyntheticConfig().descriptor(), [], open_error=DeviceConnectionError("no dongle"))

    service = AcquisitionService(factory, hub, clock, reconnect=FAST_RECONNECT)

    async def scenario() -> None:
        await service.start()
        await asyncio.wait_for(service.wait(), 5)

    asyncio.run(scenario())
    assert len(opens) == 4  # first attempt + 3 retries
    assert [b - a for a, b in itertools.pairwise(opens)] == [100_000, 200_000, 400_000]
    assert service.state is AcquisitionState.FAILED
    assert service.status().error.code == "device-connection-failed"  # type: ignore[union-attr]


def test_malformed_duplicate_and_overlapping_blocks_are_rejected() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    descriptor = SyntheticConfig().descriptor()
    scripted = [
        block(0),
        block(5, channels=3),  # wrong channel count
        block(5, value=float("nan")),  # non-finite
        block(5),
        block(5),  # duplicate
        block(8),  # overlaps 5..9
        block(10),
    ]
    adapter = ScriptedAdapter(descriptor, scripted)
    service = AcquisitionService(lambda: adapter, hub, clock)

    async def scenario() -> list[StreamEvent]:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 100)
        await service.start()
        await asyncio.wait_for(service.wait(), 5)
        events = []
        while (event := await sub.get(timeout=0)) is not None:
            events.append(event)
        return events

    events = asyncio.run(scenario())
    accepted = [e for e in events if isinstance(e, StreamBlock)]
    assert [b.block.first_sample_index for b in accepted] == [0, 5, 10]
    assert [b.block_sequence for b in accepted] == [0, 1, 2]
    assert isinstance(events[-1], StreamClosed)
    status = service.status()
    assert status.rejected_blocks == 4
    assert status.state is AcquisitionState.STOPPED  # finite source ended normally
    assert adapter.closed


def test_first_block_gap_is_relative_to_stream_start() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    service = AcquisitionService(lambda: ScriptedAdapter(SyntheticConfig().descriptor(), [block(3)]), hub, clock)

    async def scenario() -> list[StreamEvent]:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 10)
        await service.start()
        await asyncio.wait_for(service.wait(), 5)
        return [e for e in [await sub.get(timeout=0) for _ in range(3)] if e is not None]

    events = asyncio.run(scenario())
    first = events[1]
    assert isinstance(first, StreamBlock) and first.dropped_samples_before == 3


def test_slow_consumer_does_not_delay_acquisition() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    service = AcquisitionService(lambda: SyntheticEegAdapter(SyntheticConfig(block_size=5), clock), hub, clock)

    async def scenario() -> None:
        slow = hub.subscribe("slow-ui", DeliveryPolicy.LIVE_VIEW, 2)
        fast = hub.subscribe("fast", DeliveryPolicy.LOSSLESS, 10_000)
        await service.start()
        received = 0
        while received < 200:
            event = await asyncio.wait_for(fast.get(), 5)
            received += isinstance(event, StreamBlock)
        await service.stop()
        assert slow.dropped_blocks >= 190
        assert slow.closed_reason == "unsubscribed" or slow.closed_reason is None

    asyncio.run(scenario())


def test_stop_cancels_cleanly_and_is_idempotent() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapters: list[SyntheticEegAdapter] = []

    def factory() -> SyntheticEegAdapter:
        adapters.append(SyntheticEegAdapter(SyntheticConfig(), clock))
        return adapters[-1]

    service = AcquisitionService(factory, hub, clock)

    async def scenario() -> None:
        await service.start()
        await service.start()  # no second task
        for _ in range(20):
            await asyncio.sleep(0)
        await service.stop()
        await service.stop()

    asyncio.run(scenario())
    assert len(adapters) == 1 and adapters[0].closed
    assert service.state is AcquisitionState.STOPPED
