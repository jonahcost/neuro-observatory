from __future__ import annotations

import asyncio

import numpy as np
import pytest

from neuro_engine.acquisition.base import SampleBlock, StreamBlock
from neuro_engine.streaming.hub import (
    MAX_PENDING_CONTROL_EVENTS,
    DeliveryPolicy,
    StreamClosed,
    StreamHub,
    SubscriptionClosed,
)


def make_block(sequence: int) -> StreamBlock:
    data = np.zeros((2, 5))
    return StreamBlock("s", sequence, 0, SampleBlock(sequence * 5, sequence * 40_000, data))


def test_publish_fans_out_in_order_to_every_subscriber() -> None:
    async def scenario() -> None:
        hub = StreamHub()
        a = hub.subscribe("a")
        b = hub.subscribe("b")
        for n in range(3):
            hub.publish(make_block(n))
        for sub in (a, b):
            got = [await sub.get(timeout=0) for _ in range(3)]
            assert [e.block_sequence for e in got if isinstance(e, StreamBlock)] == [0, 1, 2]
            assert await sub.get(timeout=0) is None

    asyncio.run(scenario())


def test_publish_is_synchronous_and_never_blocks_on_consumers() -> None:
    hub = StreamHub()
    hub.subscribe("never-reads", DeliveryPolicy.LIVE_VIEW, 2)
    for n in range(10_000):
        hub.publish(make_block(n))  # would hang if publish awaited a slow consumer


def test_live_view_drops_oldest_blocks_and_counts_them() -> None:
    async def scenario() -> None:
        hub = StreamHub()
        sub = hub.subscribe("slow", DeliveryPolicy.LIVE_VIEW, 3)
        for n in range(10):
            hub.publish(make_block(n))
        assert sub.dropped_blocks == 7
        got = [await sub.get(timeout=0) for _ in range(3)]
        assert [e.block_sequence for e in got if isinstance(e, StreamBlock)] == [7, 8, 9]

    asyncio.run(scenario())


def test_live_view_never_drops_control_events() -> None:
    async def scenario() -> None:
        hub = StreamHub()
        sub = hub.subscribe("slow", DeliveryPolicy.LIVE_VIEW, 1)
        hub.publish(make_block(0))
        hub.publish(StreamClosed("s"))
        hub.publish(make_block(1))
        first = await sub.get(timeout=0)
        second = await sub.get(timeout=0)
        assert isinstance(first, StreamClosed)
        assert isinstance(second, StreamBlock) and second.block_sequence == 1
        assert sub.dropped_blocks == 1

    asyncio.run(scenario())


def test_lossless_overflow_fails_explicitly_after_draining() -> None:
    async def scenario() -> None:
        hub = StreamHub()
        sub = hub.subscribe("recorder", DeliveryPolicy.LOSSLESS, 2)
        for n in range(3):
            hub.publish(make_block(n))
        assert sub.closed_reason is not None and "overflow" in sub.closed_reason
        assert hub.subscriber_count == 0
        assert sub.dropped_blocks == 0
        assert [(await sub.get(timeout=0)).block_sequence for _ in range(2)] == [0, 1]  # type: ignore[union-attr]
        with pytest.raises(SubscriptionClosed):
            await sub.get(timeout=0)

    asyncio.run(scenario())


def test_control_event_backlog_is_bounded() -> None:
    hub = StreamHub()
    sub = hub.subscribe("stuck")
    for _ in range(MAX_PENDING_CONTROL_EVENTS + 1):
        hub.publish(StreamClosed("s"))
    assert sub.closed_reason is not None
    assert sub.pending == MAX_PENDING_CONTROL_EVENTS


def test_get_waits_for_new_events_and_unsubscribe_wakes_waiters() -> None:
    async def scenario() -> None:
        hub = StreamHub()
        sub = hub.subscribe("waiter")
        waiter = asyncio.create_task(sub.get())
        await asyncio.sleep(0)
        hub.publish(make_block(0))
        event = await asyncio.wait_for(waiter, 1)
        assert isinstance(event, StreamBlock)
        blocked = asyncio.create_task(sub.get())
        await asyncio.sleep(0)
        hub.unsubscribe(sub)
        with pytest.raises(SubscriptionClosed):
            await asyncio.wait_for(blocked, 1)
        hub.publish(make_block(1))
        assert sub.pending == 0

    asyncio.run(scenario())
