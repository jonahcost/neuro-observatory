"""FastAPI application factory. Acquisition is owned by the app lifespan, not by clients."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from neuro_engine.acquisition.base import DeviceAdapter
from neuro_engine.acquisition.clock import Clock, MonotonicClock
from neuro_engine.acquisition.service import AcquisitionService
from neuro_engine.acquisition.synthetic import SyntheticEegAdapter
from neuro_engine.analysis.band_power import (
    BandPowerAnalyzer,
    FindingStore,
    observe_acquisition_health,
)
from neuro_engine.api import anatomy, assistant, http, ws
from neuro_engine.assistant.runtime import LlamaRuntime
from neuro_engine.assistant.service import AssistantService
from neuro_engine.assistant.session import SessionController
from neuro_engine.config import EngineSettings
from neuro_engine.datasets.storage import resolve_data_root
from neuro_engine.streaming.hub import StreamHub


@dataclass(frozen=True, slots=True)
class EngineRuntime:
    settings: EngineSettings
    clock: Clock
    hub: StreamHub
    service: AcquisitionService
    session: SessionController
    analyzer: BandPowerAnalyzer
    findings: FindingStore
    assistant: AssistantService
    model: LlamaRuntime


def default_adapter_factory(settings: EngineSettings, clock: Clock) -> Callable[[], DeviceAdapter]:
    return lambda: SyntheticEegAdapter(settings.synthetic, clock)


def create_app(
    settings: EngineSettings | None = None,
    *,
    clock: Clock | None = None,
    adapter_factory: Callable[[], DeviceAdapter] | None = None,
) -> FastAPI:
    resolved_settings = settings or EngineSettings.from_env()
    resolved_clock = clock or MonotonicClock()
    factory = adapter_factory or default_adapter_factory(resolved_settings, resolved_clock)
    holder: dict[str, EngineRuntime] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub = StreamHub()
        findings = FindingStore()
        band = BandPowerAnalyzer(findings)
        data_root = resolve_data_root(resolved_settings.data_dir)
        model = LlamaRuntime(
            data_root.path,
            port=resolved_settings.assistant_port,
            enabled=resolved_settings.assistant_enabled,
        )
        service = AcquisitionService(factory, hub, resolved_clock, reconnect=resolved_settings.reconnect)
        observe_acquisition_health(service, band)
        session = SessionController(
            service,
            resolved_settings,
            resolved_clock,
            data_root.path / "recordings",
            band,
            on_cancel=model.cancel,
        )
        assistant_service = AssistantService(session, findings, model)
        runtime = EngineRuntime(
            resolved_settings,
            resolved_clock,
            hub,
            service,
            session,
            band,
            findings,
            assistant_service,
            model,
        )
        app.state.engine = runtime
        holder["engine"] = runtime
        await model.startup()
        await service.start()
        try:
            yield
        finally:
            await model.shutdown()
            await service.stop()
            holder.pop("engine", None)

    app = FastAPI(title="Neuro Observatory Engine", lifespan=lifespan)
    app.include_router(http.router)
    app.include_router(ws.router)
    app.mount(anatomy.MOUNT_PATH, anatomy.create_anatomy_app(resolved_settings))
    app.mount(assistant.MOUNT_PATH, assistant.create_assistant_app(holder, resolved_settings))
    return app
