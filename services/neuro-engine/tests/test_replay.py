from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from neuro_engine.acquisition.base import (
    ChannelSpec,
    DeviceInfo,
    StreamDescriptor,
    SyntheticProvenance,
)
from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.replay import ReplayEegAdapter
from neuro_engine.acquisition.service import AcquisitionService
from neuro_engine.acquisition.synthetic import SyntheticConfig
from neuro_engine.analysis.band_power import BandPowerAnalyzer, FindingStore
from neuro_engine.assistant.session import SessionController
from neuro_engine.config import EngineSettings
from neuro_engine.recordings.scenario import write_alpha_step
from neuro_engine.recordings.v1 import (
    Gap,
    RecordingError,
    _manifest_sha256,
    read_recording,
    write_recording,
)
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


def _tiny_descriptor() -> StreamDescriptor:
    return StreamDescriptor(
        device=DeviceInfo(kind="synthetic", model="gap-fixture", device_id="gap-fixture", adapter_version="1.0.0"),
        channels=tuple(ChannelSpec(label=f"Ch{index}", reference="synthetic") for index in range(2)),
        nominal_sample_rate_hz=125.0,
        timestamp_source="synthetic-nominal",
        provenance=SyntheticProvenance(
            generator="test",
            generator_version="1",
            seed=1,
            config_hash="sha256:" + "ab" * 32,
        ),
    )


def test_replay_keeps_declared_gap_indexes(tmp_path: Path) -> None:
    samples = np.arange(2 * 100, dtype=np.float64).reshape(2, 100)
    recording = write_recording(tmp_path / "gapped", samples, _tiny_descriptor(), recording_id="gapped", gaps=(Gap(40, 10),))
    clock = VirtualClock()

    async def collect() -> list[tuple[int, float]]:
        adapter = ReplayEegAdapter(recording, clock, block_size=25)
        await adapter.open()
        emitted: list[tuple[int, float]] = []
        async for block in adapter.blocks():
            for offset in range(block.sample_count):
                emitted.append((block.first_sample_index + offset, float(block.data[0, offset])))
        await adapter.close()
        return emitted

    emitted = asyncio.run(collect())
    indexes = [index for index, _value in emitted]
    assert indexes[:40] == list(range(40))
    assert 40 not in indexes and 49 not in indexes
    assert indexes[40] == 50
    assert emitted[40][1] == 40.0
    assert indexes[-1] == 109


def test_pause_holds_the_replay_schedule(tmp_path: Path) -> None:
    recording, _step = write_alpha_step(tmp_path / "alpha-step")

    class WallClock:
        def __init__(self) -> None:
            self.now = 1_000_000
            self.delays: list[int] = []

        def monotonic_us(self) -> int:
            return self.now

        def unix_time_us(self) -> int:
            return self.now

        def advance(self, delta_us: int) -> None:
            self.now += delta_us

        async def sleep_until(self, deadline_us: int) -> None:
            self.delays.append(deadline_us - self.now)
            self.now = max(self.now, deadline_us)
            await asyncio.sleep(0)

    clock = WallClock()

    async def run() -> int:
        pause = asyncio.Event()
        pause.set()
        adapter = ReplayEegAdapter(recording, clock, pause=pause, block_size=25)
        await adapter.open()
        blocks = adapter.blocks()
        await anext(blocks)
        pause.clear()
        pending = asyncio.create_task(anext(blocks))
        await asyncio.sleep(0)
        assert pending.done() is False
        clock.advance(5_000_000)
        pause.set()
        await pending
        await adapter.close()
        return clock.delays[-1]

    delay_us = asyncio.run(run())
    assert delay_us >= 200_000


def test_manifest_checksum_binds_gaps_and_channel_indexes(tmp_path: Path) -> None:
    samples = np.ones((2, 20), dtype=np.float64)
    directory = tmp_path / "bound"
    write_recording(directory, samples, _tiny_descriptor(), recording_id="bound")
    manifest_path = directory / "manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["gaps"] = [{"firstIndex": 4, "count": 2}]
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RecordingError) as mismatch:
        read_recording(directory)
    assert mismatch.value.code == "checksum-mismatch"

    document["channels"][0]["index"] = 1
    document["manifestSha256"] = _manifest_sha256(document)
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RecordingError) as indexes:
        read_recording(directory)
    assert indexes.value.code == "invalid-manifest"
