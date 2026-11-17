"""Switch the acquisition source. Seek reopens the adapter and starts a new stream."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from neuro_engine.acquisition.clock import Clock
from neuro_engine.acquisition.replay import ReplayEegAdapter
from neuro_engine.acquisition.service import AcquisitionService
from neuro_engine.acquisition.synthetic import SyntheticEegAdapter
from neuro_engine.analysis.band_power import BandPowerAnalyzer
from neuro_engine.config import EngineSettings
from neuro_engine.recordings.v1 import RecordingError, resolve_recording


class SessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SessionController:
    def __init__(
        self,
        service: AcquisitionService,
        settings: EngineSettings,
        clock: Clock,
        recordings_root: Path,
        analyzer: BandPowerAnalyzer,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        self.service = service
        self.settings = settings
        self.clock = clock
        self.recordings_root = recordings_root
        self.analyzer = analyzer
        self.generation = 0
        self.source = "synthetic"
        self.recording_id: str | None = None
        self.paused = False
        self._pause = asyncio.Event()
        self._pause.set()
        self._lock = asyncio.Lock()
        self._cancel: asyncio.Event = asyncio.Event()
        self._on_cancel = on_cancel
        analyzer.set_context(0, None)

    def request_cancel(self) -> None:
        self._cancel.set()
        if self._on_cancel is not None:
            self._on_cancel()

    def take_cancel(self) -> bool:
        if self._cancel.is_set():
            self._cancel.clear()
            return True
        return False

    async def use_synthetic(self) -> None:
        settings = self.settings

        def factory() -> SyntheticEegAdapter:
            return SyntheticEegAdapter(settings.synthetic, self.clock)

        await self._restart(factory, source="synthetic", recording_id=None, keep_baseline=False)

    async def replay(self, recording_id: str, *, start_index: int = 0, keep_baseline: bool = False) -> None:
        try:
            recording = resolve_recording(self.recordings_root, recording_id)
        except RecordingError as exc:
            raise SessionError(exc.code, exc.message) from exc
        if start_index < 0:
            raise SessionError("invalid-seek", "sample index must be non-negative")

        def factory() -> ReplayEegAdapter:
            return ReplayEegAdapter(
                recording,
                self.clock,
                start_index=start_index,
                pause=self._pause,
            )

        await self._restart(
            factory,
            source="replay",
            recording_id=recording.recording_id,
            keep_baseline=keep_baseline,
        )

    async def seek(self, sample_index: int) -> None:
        if self.source != "replay" or self.recording_id is None:
            raise SessionError(
                "not-replay",
                "Seek is available during replay. The live synthetic stream has no earlier segment to open.",
            )
        await self.replay(self.recording_id, start_index=sample_index, keep_baseline=False)

    async def pause(self) -> None:
        if self.source != "replay":
            raise SessionError("not-replay", "The live synthetic stream keeps running.")
        self.paused = True
        self._pause.clear()

    async def resume(self) -> None:
        self.paused = False
        self._pause.set()

    async def _restart(self, factory, *, source: str, recording_id: str | None, keep_baseline: bool) -> None:
        async with self._lock:
            self.generation += 1
            self.request_cancel()
            await self.service.stop()
            self.source = source
            self.recording_id = recording_id
            self.paused = False
            self._pause.set()
            self.analyzer.set_context(self.generation, recording_id)
            self.analyzer.prepare_restart(keep_baseline=keep_baseline)
            self.service.set_adapter_factory(factory)
            await self.service.start()
