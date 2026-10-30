"""Conversion from acquisition types to protocol v2 messages."""

from __future__ import annotations

from neuro_engine.acquisition.base import ActiveStream, StreamBlock
from neuro_engine.acquisition.base import SyntheticProvenance as SyntheticSource
from neuro_engine.acquisition.service import AcquisitionStatus
from neuro_engine.protocol import v2


def metadata_message(stream: ActiveStream) -> v2.StreamMetadata:
    descriptor = stream.descriptor
    source = descriptor.provenance
    provenance: v2.SyntheticProvenance | v2.DeviceProvenance
    if isinstance(source, SyntheticSource):
        provenance = v2.SyntheticProvenance(
            kind="synthetic",
            generator=source.generator,
            generator_version=source.generator_version,
            seed=source.seed,
            config_hash=source.config_hash,
        )
    else:
        provenance = v2.DeviceProvenance(kind="device")
    device = descriptor.device
    return v2.StreamMetadata(
        type="stream.metadata",
        schema_version=v2.SCHEMA_VERSION,
        stream_id=stream.stream_id,
        device=v2.DeviceInfo(
            kind=device.kind,
            model=device.model,
            device_id=device.device_id,
            adapter_version=device.adapter_version,
            firmware_version=device.firmware_version,
        ),
        provenance=provenance,
        nominal_sample_rate_hz=float(descriptor.nominal_sample_rate_hz),
        layout="channel-major",
        channels=[
            v2.ChannelSpec(index=i, label=c.label, type=c.type, unit=c.unit, reference=c.reference)
            for i, c in enumerate(descriptor.channels)
        ],
        timebase=v2.Timebase(
            clock="engine-monotonic",
            unit="us",
            timestamp_source=descriptor.timestamp_source,
            anchor=v2.ClockAnchor(
                monotonic_us=stream.anchor_monotonic_us,
                unix_time_us=stream.anchor_unix_time_us,
            ),
        ),
    )


def block_message(event: StreamBlock) -> v2.EegBlock:
    block = event.block
    return v2.EegBlock(
        type="eeg.block",
        schema_version=v2.SCHEMA_VERSION,
        stream_id=event.stream_id,
        block_sequence=event.block_sequence,
        first_sample_index=block.first_sample_index,
        sample_count=block.sample_count,
        first_sample_time_us=block.first_sample_time_us,
        dropped_samples_before=event.dropped_samples_before,
        samples=block.data.tolist(),
    )


def status_message(status: AcquisitionStatus, blocks_dropped_for_client: int = 0) -> v2.StreamStatus:
    return v2.StreamStatus(
        type="stream.status",
        schema_version=v2.SCHEMA_VERSION,
        stream_id=status.stream_id,
        state=status.state.value,
        at_us=status.at_us,
        counters=v2.StreamCounters(
            samples_acquired=status.samples_acquired,
            acquisition_gap_samples=status.acquisition_gap_samples,
            rejected_blocks=status.rejected_blocks,
            blocks_dropped_for_client=blocks_dropped_for_client,
            effective_sample_rate_hz=status.effective_sample_rate_hz,
        ),
        error=(
            v2.StreamError(code=status.error.code, message=status.error.message[:500])
            if status.error is not None
            else None
        ),
    )
