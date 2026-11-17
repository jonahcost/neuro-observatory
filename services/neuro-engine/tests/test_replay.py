from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.replay import ReplayEegAdapter
from neuro_engine.acquisition.service import AcquisitionService
from neuro_engine.acquisition.synthetic import SyntheticConfig
from neuro_engine.analysis.band_power import BandPowerAnalyzer, FindingStore
from neuro_engine.assistant.session import SessionController
from neuro_engine.config import EngineSettings
from neuro_engine.recordings.scenario import write_alpha_step
from neuro_engine.recordings.v1 import read_recording
from neuro_engine.streaming.hub import StreamHub


def test_replay_matches_the_file_and_keeps_the_alpha_step(tmp_path: Path) -> None:
    directory = tmp_path / "alpha-step"
    written, step = write_alpha_step(directory)
    loaded = read_recording(directory)
    assert loaded.recording_id == "alpha-step"
    assert np.array_equal(loaded.samples, written.samples)
    clock = VirtualClock()

    async def collect() -> list[tuple[int, np.ndarray]]:
        adapter = ReplayEegAdapter(loaded, clock)
        await adapter.open()
        blocks = []
        async for block in adapter.blocks():
            blocks.append((block.first_sample_index, block.data.copy()))
        await adapter.close()
        return blocks

    blocks = asyncio.run(collect())
    assert blocks[0][0] == 0
    joined = np.concatenate([data for _, data in blocks], axis=1)
    assert np.array_equal(joined, loaded.samples)
    o1 = loaded.descriptor.channels and next(
        index for index, channel in enumerate(loaded.descriptor.channels) if channel.label == "O1"
    )
    before = float(np.std(loaded.samples[o1, :step]))
    after = float(np.std(loaded.samples[o1, step:]))
    assert after > before * 2
    # The live synthetic default is a different seed and is not this recording.
    assert SyntheticConfig().seed == 0
    assert loaded.descriptor.provenance.seed == 1  # type: ignore[union-attr]


def test_seek_reopens_and_issues_a_new_stream(tmp_path: Path) -> None:
    write_alpha_step(tmp_path / "recordings" / "alpha-step")
    clock = VirtualClock()
    hub = StreamHub()
    settings = EngineSettings()
    service = AcquisitionService(lambda: pytest.fail("initial factory should be replaced"), hub, clock)  # type: ignore[arg-type]
    analyzer = BandPowerAnalyzer(FindingStore())
    service.add_accepted_listener(analyzer.on_accepted)
    session = SessionController(service, settings, clock, tmp_path / "recordings", analyzer)

    async def run() -> tuple[str | None, str | None]:
        await session.replay("alpha-step", start_index=0)
        await asyncio.sleep(0)
        for _ in range(5):
            await asyncio.sleep(0)
            if analyzer.newest_index is not None:
                break
        first = None if service.current_stream is None else service.current_stream.stream_id
        await session.seek(1000)
        await asyncio.sleep(0)
        second = None if service.current_stream is None else service.current_stream.stream_id
        await service.stop()
        return first, second

    first, second = asyncio.run(run())
    assert first is not None and second is not None
    assert first != second
    assert session.generation == 2
