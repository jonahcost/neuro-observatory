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
from neuro_engine.api import http, ws
from neuro_engine.config import EngineSettings
from neuro_engine.streaming.hub import StreamHub


@dataclass(frozen=True, slots=True)
class EngineRuntime:
    settings: EngineSettings
    clock: Clock
    hub: StreamHub
    service: AcquisitionService


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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub = StreamHub()
        service = AcquisitionService(factory, hub, resolved_clock, reconnect=resolved_settings.reconnect)
        app.state.engine = EngineRuntime(resolved_settings, resolved_clock, hub, service)
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(title="Neuro Observatory Engine", lifespan=lifespan)
    app.include_router(http.router)
    app.include_router(ws.router)
    return app
