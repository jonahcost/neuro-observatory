from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

from neuro_engine.acquisition.base import SyntheticProvenance
from neuro_engine.protocol import v2
from neuro_engine.protocol.convert import metadata_message, status_message

if TYPE_CHECKING:
    from neuro_engine.app import EngineRuntime

router = APIRouter()


def _runtime(request: Request) -> EngineRuntime:
    return request.app.state.engine


# Handlers are `async def` so they run on the event loop that owns acquisition state.
@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    service = _runtime(request).service
    status = service.status()
    health = service.health()
    stream = service.current_stream
    descriptor = stream.descriptor if stream else None
    return {
        "status": "ok" if health.ok else "degraded",
        "degradedReasons": list(health.reasons),
        "service": "neuro-engine",
        "protocolVersion": v2.SCHEMA_VERSION,
        "acquisition": {
            "state": status.state.value,
            "streamId": status.stream_id,
            "deviceKind": descriptor.device.kind if descriptor else None,
            "synthetic": isinstance(descriptor.provenance, SyntheticProvenance) if descriptor else None,
            "channelCount": descriptor.channel_count if descriptor else None,
            "nominalSampleRateHz": descriptor.nominal_sample_rate_hz if descriptor else None,
            "counters": {
                "samplesAcquired": status.samples_acquired,
                "acquisitionGapSamples": status.acquisition_gap_samples,
                "rejectedBlocks": status.rejected_blocks,
                "effectiveSampleRateHz": status.effective_sample_rate_hz,
            },
        },
    }


@router.get("/api/v2/stream")
async def stream(request: Request) -> dict[str, Any]:
    service = _runtime(request).service
    current = service.current_stream
    return {
        "metadata": v2.to_wire_dict(metadata_message(current)) if current else None,
        "status": v2.to_wire_dict(status_message(service.status())),
    }
