from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from neuro_engine.acquisition.base import (
    MAX_SAFE_INTEGER,
    DeviceConfigError,
    DeviceConnectionError,
    DeviceDisconnectedError,
    DeviceInfo,
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


class PacedAdapter:
    """Adapter releasing `make_block(n)` every `period_us` of virtual time, then holding or ending."""

    def __init__(
        self,
        clock: VirtualClock,
        make_block: Callable[[int], SampleBlock],
        count: int,
        *,
        period_us: int = 40_000,
        then: str = "hold",
        close_error: Exception | None = None,
        descriptor: StreamDescriptor | None = None,
    ) -> None:
        self._clock = clock
        self._make_block = make_block
        self._count = count
        self._period_us = period_us
        self._then = then
        self._close_error = close_error
        self._descriptor = descriptor or SyntheticConfig().descriptor()
        self.closed = False

    async def open(self) -> StreamDescriptor:
        return self._descriptor

    async def blocks(self) -> AsyncIterator[SampleBlock]:
        start = self._clock.monotonic_us()
        for n in range(self._count):
            await self._clock.sleep_until(start + (n + 1) * self._period_us)
            yield self._make_block(n)
        if self._then == "disconnect":
            raise DeviceDisconnectedError("unplugged")
        if self._then == "hold":
            await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


async def settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


def test_close_failure_keeps_the_retryable_cause_and_reconnects() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapters: list[PacedAdapter] = []

    def factory() -> PacedAdapter:
        first = not adapters
        adapters.append(
            PacedAdapter(
                clock,
                lambda n: block(n * 5),
                count=2 if first else 3,
                then="disconnect" if first else "hold",
                close_error=RuntimeError("release_session failed") if first else None,
            )
        )
        return adapters[-1]

    service = AcquisitionService(factory, hub, clock, reconnect=FAST_RECONNECT, stream_id_factory=sequential_ids())

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) and e.stream_id == "stream-2" for e in ev) >= 3)
        assert [type(e).__name__ for e in events[:4]] == ["StreamOpened", "StreamBlock", "StreamBlock", "StreamClosed"]
        assert isinstance(events[4], StreamOpened) and events[4].stream.stream_id == "stream-2"
        assert service.state is AcquisitionState.STREAMING
        assert service.current_stream is not None and service.current_stream.stream_id == "stream-2"
        await service.stop()

    asyncio.run(scenario())
    assert len(adapters) == 2 and all(a.closed for a in adapters)
    assert service.current_stream is None


def test_close_failure_after_a_disconnect_reports_the_disconnect() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapter = PacedAdapter(clock, lambda n: block(n * 5), 1, then="disconnect", close_error=RuntimeError("busy"))
    no_retry = ReconnectPolicy(initial_delay_s=0.1, max_delay_s=0.1, max_attempts=0)
    service = AcquisitionService(lambda: adapter, hub, clock, reconnect=no_retry)

    async def scenario() -> list[StreamEvent]:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 100)
        await service.start()
        await asyncio.wait_for(service.wait(), 5)
        return [e for e in [await sub.get(timeout=0) for _ in range(4)] if e is not None]

    events = asyncio.run(scenario())
    assert isinstance(events[-1], StreamClosed)
    assert service.current_stream is None
    assert service.status().error.code == "device-disconnected"  # type: ignore[union-attr]


def test_stop_does_not_raise_when_close_fails() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapter = PacedAdapter(clock, lambda n: block(n * 5), 10**6, close_error=RuntimeError("busy"))
    service = AcquisitionService(lambda: adapter, hub, clock)

    async def scenario() -> list[StreamEvent]:
        sub = hub.subscribe("test", DeliveryPolicy.LIVE_VIEW, 5)
        await service.start()
        await settle()
        await service.stop()
        events = []
        while (event := await sub.get(timeout=0)) is not None:
            events.append(event)
        return events

    events = asyncio.run(scenario())
    assert isinstance(events[-1], StreamClosed)
    assert adapter.closed and service.state is AcquisitionState.STOPPED and service.current_stream is None


def test_descriptor_outside_protocol_limits_fails_without_retry() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    calls = 0

    class VendorKindAdapter(ScriptedAdapter):
        async def open(self) -> StreamDescriptor:
            nonlocal calls
            calls += 1
            device = DeviceInfo(kind="OpenBCI", model="Cyton", device_id="x", adapter_version="1")
            return StreamDescriptor(device, self.descriptor.channels, 250.0, "host-receipt-fitted", self.descriptor.provenance)

    service = AcquisitionService(
        lambda: VendorKindAdapter(SyntheticConfig().descriptor(), []), hub, clock, reconnect=FAST_RECONNECT
    )

    async def scenario() -> None:
        await service.start()
        await asyncio.wait_for(service.wait(), 5)

    asyncio.run(scenario())
    assert calls == 1
    assert service.state is AcquisitionState.FAILED
    assert service.status().error.code == "invalid-device-config"  # type: ignore[union-attr]
    assert service.health().reasons == ("not-streaming",)


def test_oversized_blocks_are_split_into_contiguous_protocol_blocks() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    rng = np.random.default_rng(3)
    data = rng.normal(size=(16, 25_000))
    stamps = np.arange(25_000, dtype=np.int64) * 8_000 + 7
    big = SampleBlock(3, 5_000_000, data, device_timestamps_us=stamps)
    service = AcquisitionService(
        lambda: ScriptedAdapter(SyntheticConfig().descriptor(), [big, block(25_003)]), hub, clock
    )

    async def scenario() -> list[StreamBlock]:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 100)
        await service.start()
        await asyncio.wait_for(service.wait(), 5)
        events = [await sub.get(timeout=0) for _ in range(7)]
        return [e for e in events if isinstance(e, StreamBlock)]

    parts = asyncio.run(scenario())
    assert [p.block_sequence for p in parts] == [0, 1, 2, 3]
    assert [p.block.sample_count for p in parts] == [10_000, 10_000, 5_000, 5]
    assert [p.block.first_sample_index for p in parts] == [3, 10_003, 20_003, 25_003]
    assert [p.dropped_samples_before for p in parts] == [3, 0, 0, 0]
    # 125 Hz: 8 000 µs per sample, the protocol's sample-time rule.
    assert [p.block.first_sample_time_us for p in parts[:3]] == [5_000_000, 85_000_000, 165_000_000]
    assert np.array_equal(np.concatenate([p.block.data for p in parts[:3]], axis=1), data)
    assert np.array_equal(np.concatenate([p.block.device_timestamps_us for p in parts[:3]]), stamps)  # type: ignore[misc]
    status = service.status()
    assert status.samples_acquired == 25_005 and status.acquisition_gap_samples == 3 and status.rejected_blocks == 0


def test_blocks_outside_the_protocol_integer_range_are_rejected() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    scripted = [
        block(0),
        SampleBlock(5, -1, np.ones((16, 5))),  # negative acquisition time
        SampleBlock(MAX_SAFE_INTEGER - 2, 0, np.ones((16, 5))),  # index range exceeds 2**53 - 1
        block(5),
    ]
    service = AcquisitionService(lambda: ScriptedAdapter(SyntheticConfig().descriptor(), scripted), hub, clock)

    async def scenario() -> list[StreamBlock]:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 100)
        await service.start()
        await asyncio.wait_for(service.wait(), 5)
        events = [await sub.get(timeout=0) for _ in range(5)]
        return [e for e in events if isinstance(e, StreamBlock)]

    accepted = asyncio.run(scenario())
    assert [b.block.first_sample_index for b in accepted] == [0, 5]
    assert service.status().rejected_blocks == 2


def test_effective_rate_does_not_depend_on_the_index_origin() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapter = PacedAdapter(clock, lambda n: block(1_000_000 + n * 5), 40)
    service = AcquisitionService(lambda: adapter, hub, clock)

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) for e in ev) >= 40)
        status = service.status()
        await service.stop()
        assert status.effective_sample_rate_hz == pytest.approx(125.0)
        # Per the adapter contract, indices start at 0 after open(): the offset is a declared gap.
        assert status.acquisition_gap_samples == 1_000_000

    asyncio.run(scenario())


def test_effective_rate_is_unknown_until_one_second_of_blocks() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapter = PacedAdapter(clock, lambda n: block(n * 5), 25)  # 25 blocks x 40 ms: 0.96 s between first and last
    service = AcquisitionService(lambda: adapter, hub, clock)

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) for e in ev) >= 25)
        assert service.status().effective_sample_rate_hz is None
        await service.stop()

    asyncio.run(scenario())


def test_health_is_ok_while_streaming_and_reports_stalls() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    adapter = PacedAdapter(clock, lambda n: block(n * 5), 10)
    service = AcquisitionService(lambda: adapter, hub, clock)

    async def scenario() -> None:
        assert service.health().reasons == ("not-streaming",)
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) for e in ev) >= 10)
        assert service.health().ok
        clock.advance(1_000_000)  # window is max(1 s, 3 x 40 ms)
        assert service.health().ok
        clock.advance(1)
        assert service.health().reasons == ("no-recent-data",)
        await service.stop()
        assert service.health().reasons == ("not-streaming",)

    asyncio.run(scenario())


def test_health_reports_no_data_when_the_first_block_never_arrives() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    service = AcquisitionService(lambda: PacedAdapter(clock, lambda n: block(n * 5), 0), hub, clock)

    async def scenario() -> None:
        await service.start()
        await settle()
        assert service.state is AcquisitionState.STREAMING and service.health().ok
        clock.advance(1_000_001)
        assert service.health().reasons == ("no-recent-data",)
        await service.stop()

    asyncio.run(scenario())


def test_health_reports_recent_rejections_until_the_window_passes() -> None:
    clock = VirtualClock()
    hub = StreamHub()

    def make(n: int) -> SampleBlock:
        return block(n * 5, value=float("nan")) if n == 1 else block(n * 5)

    adapter = PacedAdapter(clock, make, 3)
    service = AcquisitionService(lambda: adapter, hub, clock)

    async def scenario() -> None:
        sub = hub.subscribe("test", DeliveryPolicy.LOSSLESS, 1000)
        events: list[StreamEvent] = []
        await service.start()
        await drain(events, sub, lambda ev: sum(isinstance(e, StreamBlock) for e in ev) >= 2)
        assert service.status().rejected_blocks == 1
        assert service.health().reasons == ("recent-rejections",)
        clock.advance(1_000_001)
        assert "recent-rejections" not in service.health().reasons
        await service.stop()

    asyncio.run(scenario())


def test_health_is_degraded_while_reconnecting() -> None:
    clock = VirtualClock()
    hub = StreamHub()
    service = AcquisitionService(
        lambda: ScriptedAdapter(SyntheticConfig().descriptor(), [], open_error=DeviceConnectionError("no dongle")),
        hub,
        clock,
        reconnect=ReconnectPolicy(initial_delay_s=3600, max_delay_s=3600),
    )

    async def scenario() -> None:
        await service.start()
        await settle()
        assert service.state is AcquisitionState.RECONNECTING
        assert service.health().reasons == ("not-streaming",)
        await service.stop()

    asyncio.run(scenario())
