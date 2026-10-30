"""Consumer-side sample-integrity tracking.

Mirrors `StreamIntegrityTracker` in packages/protocol/src/integrity.ts; both run
the shared fixtures in packages/protocol/fixtures/v2/integrity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from neuro_engine.protocol.v2 import EegBlock, StreamMetadata

MetadataVerdict = Literal["new-stream", "same-stream"]
BlockVerdict = Literal["accepted", "duplicate", "out-of-order", "unknown-stream"]


@dataclass(slots=True)
class IntegrityCounters:
    streams_started: int = 0
    blocks_accepted: int = 0
    samples_accepted: int = 0
    acquisition_gap_samples: int = 0
    transport_dropped_blocks: int = 0
    transport_gap_samples: int = 0
    inconsistent_blocks: int = 0
    duplicate_blocks: int = 0
    out_of_order_blocks: int = 0
    unknown_stream_blocks: int = 0

    def as_wire_dict(self) -> dict[str, int]:
        return {_camel(key): value for key, value in asdict(self).items()}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


class StreamIntegrityTracker:
    def __init__(self) -> None:
        self._stream_id: str | None = None
        self._next_block_sequence: int | None = None
        self._next_sample_index: int | None = None
        self._counters = IntegrityCounters()

    def on_metadata(self, metadata: StreamMetadata) -> MetadataVerdict:
        if metadata.stream_id == self._stream_id:
            return "same-stream"
        self._stream_id = metadata.stream_id
        self._next_block_sequence = None
        self._next_sample_index = None
        self._counters.streams_started += 1
        return "new-stream"

    def on_block(self, block: EegBlock) -> BlockVerdict:
        c = self._counters
        if self._stream_id is None or block.stream_id != self._stream_id:
            c.unknown_stream_blocks += 1
            return "unknown-stream"
        if self._next_block_sequence is not None and self._next_sample_index is not None:
            if block.block_sequence < self._next_block_sequence:
                if block.block_sequence == self._next_block_sequence - 1:
                    c.duplicate_blocks += 1
                    return "duplicate"
                c.out_of_order_blocks += 1
                return "out-of-order"
            if block.first_sample_index < self._next_sample_index:
                c.out_of_order_blocks += 1
                return "out-of-order"
            missing = block.first_sample_index - self._next_sample_index
            skipped = block.block_sequence - self._next_block_sequence
            if skipped > 0:
                c.transport_dropped_blocks += skipped
                c.transport_gap_samples += max(0, missing - block.dropped_samples_before)
                if missing < block.dropped_samples_before:
                    c.inconsistent_blocks += 1
            elif missing != block.dropped_samples_before:
                c.inconsistent_blocks += 1
        c.blocks_accepted += 1
        c.samples_accepted += block.sample_count
        c.acquisition_gap_samples += block.dropped_samples_before
        self._next_block_sequence = block.block_sequence + 1
        self._next_sample_index = block.first_sample_index + block.sample_count
        return "accepted"

    def snapshot(self) -> IntegrityCounters:
        return IntegrityCounters(**asdict(self._counters))
