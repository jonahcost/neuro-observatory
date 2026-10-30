"""Bounded fan-out of acquisition events to independent consumers.

`StreamHub.publish` never awaits, so no consumer can delay acquisition. Each
subscriber has its own bounded queue and an explicit overflow policy. All
methods must be called from the event loop thread.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from neuro_engine.acquisition.base import ActiveStream, StreamBlock

MAX_PENDING_CONTROL_EVENTS = 32


@dataclass(frozen=True, slots=True)
class StreamOpened:
    stream: ActiveStream


@dataclass(frozen=True, slots=True)
class StreamClosed:
    stream_id: str


StreamEvent = StreamOpened | StreamBlock | StreamClosed


class DeliveryPolicy(StrEnum):
    LIVE_VIEW = "live-view"
    """Drop the oldest pending block on overflow and count it (UI clients)."""
    LOSSLESS = "lossless"
    """Close the subscription on overflow; never drop silently (recorder)."""


class SubscriptionClosed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Subscription:
    def __init__(self, name: str, policy: DeliveryPolicy, max_pending_blocks: int) -> None:
        if max_pending_blocks < 1:
            raise ValueError("max_pending_blocks must be >= 1")
        self.name = name
        self.policy = policy
        self.max_pending_blocks = max_pending_blocks
        self.dropped_blocks = 0
        self._items: deque[StreamEvent] = deque()
        self._pending_blocks = 0
        self._pending_control = 0
        self._wakeup = asyncio.Event()
        self._closed_reason: str | None = None

    @property
    def closed_reason(self) -> str | None:
        return self._closed_reason

    @property
    def pending(self) -> int:
        return len(self._items)

    def close(self, reason: str) -> None:
        if self._closed_reason is None:
            self._closed_reason = reason
        self._wakeup.set()

    def offer(self, event: StreamEvent) -> None:
        if self._closed_reason is not None:
            return
        if isinstance(event, StreamBlock):
            if self._pending_blocks >= self.max_pending_blocks:
                if self.policy is DeliveryPolicy.LOSSLESS:
                    self.close(f"overflow: more than {self.max_pending_blocks} blocks pending")
                    return
                self._drop_oldest_block()
            self._pending_blocks += 1
        else:
            if self._pending_control >= MAX_PENDING_CONTROL_EVENTS:
                self.close("overflow: too many pending control events")
                return
            self._pending_control += 1
        self._items.append(event)
        self._wakeup.set()

    def _drop_oldest_block(self) -> None:
        for position, item in enumerate(self._items):
            if isinstance(item, StreamBlock):
                del self._items[position]
                self._pending_blocks -= 1
                self.dropped_blocks += 1
                return

    async def get(self, timeout: float | None = None) -> StreamEvent | None:
        """Next event in order; None on timeout. Raises SubscriptionClosed once drained after close."""
        while not self._items:
            if self._closed_reason is not None:
                raise SubscriptionClosed(self._closed_reason)
            self._wakeup.clear()
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout)
            except TimeoutError:
                return None
        item = self._items.popleft()
        if isinstance(item, StreamBlock):
            self._pending_blocks -= 1
        else:
            self._pending_control -= 1
        return item


class StreamHub:
    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    def subscribe(
        self,
        name: str,
        policy: DeliveryPolicy = DeliveryPolicy.LIVE_VIEW,
        max_pending_blocks: int = 25,
    ) -> Subscription:
        subscription = Subscription(name, policy, max_pending_blocks)
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subscription.close("unsubscribed")
        self._subscriptions.discard(subscription)

    def publish(self, event: StreamEvent) -> None:
        for subscription in list(self._subscriptions):
            subscription.offer(event)
            if subscription.closed_reason is not None:
                self._subscriptions.discard(subscription)
