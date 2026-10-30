import asyncio
import time
from collections.abc import AsyncIterator

import numpy as np
from fastapi.testclient import TestClient

from neuro_engine.acquisition.base import SampleBlock, StreamDescriptor
from neuro_engine.acquisition.synthetic import SyntheticConfig
from neuro_engine.app import create_app
from neuro_engine.config import EngineSettings


def test_health():
    with TestClient(create_app(EngineSettings())) as client:
        time.sleep(0.05)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["degradedReasons"] == []
    assert body["protocolVersion"] == 2
    acquisition = body["acquisition"]
    assert acquisition["state"] == "streaming"
    assert acquisition["deviceKind"] == "synthetic"
    assert acquisition["synthetic"] is True
    assert acquisition["channelCount"] == 16
    assert acquisition["nominalSampleRateHz"] == 125
    assert set(acquisition["counters"]) == {
        "samplesAcquired",
        "acquisitionGapSamples",
        "rejectedBlocks",
        "effectiveSampleRateHz",
    }


class RejectedDataAdapter:
    """Delivers blocks with a non-finite channel, so every block is rejected."""

    async def open(self) -> StreamDescriptor:
        return SyntheticConfig(channel_labels=("C3", "C4")).descriptor()

    async def blocks(self) -> AsyncIterator[SampleBlock]:
        for n in range(10**6):
            await asyncio.sleep(0.01)
            yield SampleBlock(n * 5, 0, np.array([[np.nan] * 5, [1.0] * 5]))

    async def close(self) -> None:
        pass


def test_health_is_degraded_when_every_block_is_rejected():
    with TestClient(create_app(EngineSettings(), adapter_factory=RejectedDataAdapter)) as client:
        time.sleep(0.2)
        body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert body["degradedReasons"] == ["recent-rejections"]
    assert body["acquisition"]["state"] == "streaming"
    assert body["acquisition"]["counters"]["samplesAcquired"] == 0
    assert body["acquisition"]["counters"]["rejectedBlocks"] > 0
