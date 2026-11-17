"""Loopback assistant HTTP API. It does not carry raw EEG samples."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from neuro_engine.assistant.session import SessionError
from neuro_engine.config import EngineSettings

MOUNT_PATH = "/api/assistant/v1"


def create_assistant_app(holder: dict[str, Any], settings: EngineSettings) -> FastAPI:
    app = FastAPI(title="Neuro Observatory assistant", openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
        allow_credentials=False,
    )

    def engine() -> Any:
        runtime = holder.get("engine")
        if runtime is None:
            raise SessionError("starting", "The engine is not ready.")
        return runtime

    @app.get("/snapshot")
    async def snapshot() -> dict[str, Any]:
        try:
            return engine().assistant.snapshot()
        except SessionError as exc:
            return _error(exc, 503)

    @app.post("/intent")
    async def intent(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return _error(SessionError("invalid-json", "Intent body must be JSON."), 400)
        if not isinstance(body, dict):
            return _error(SessionError("invalid-json", "Intent body must be an object."), 400)
        try:
            result = await engine().assistant.intent(body)
        except SessionError as exc:
            return _error(exc, 503)
        return JSONResponse(result)

    @app.post("/session")
    async def session_command(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return _error(SessionError("invalid-json", "Session body must be JSON."), 400)
        if not isinstance(body, dict):
            return _error(SessionError("invalid-json", "Session body must be an object."), 400)
        try:
            runtime = engine()
            action = body.get("action")
            if action == "replay":
                await runtime.session.replay(
                    str(body.get("recordingId") or ""),
                    start_index=int(body.get("startSampleIndex") or 0),
                    keep_baseline=bool(body.get("keepBaseline")),
                )
            elif action == "synthetic":
                await runtime.session.use_synthetic()
            elif action == "pause":
                await runtime.session.pause()
            elif action == "resume":
                await runtime.session.resume()
            elif action == "seek":
                await runtime.session.seek(int(body.get("sampleIndex")))
            else:
                return _error(SessionError("unknown-action", "Unsupported session action."), 400)
        except SessionError as exc:
            status = 404 if exc.code == "unknown-recording" else 400
            return _error(exc, status)
        except (TypeError, ValueError):
            return _error(SessionError("invalid-argument", "Session arguments are the wrong type."), 400)
        return JSONResponse(runtime.assistant.snapshot())

    return app


def _error(exc: SessionError, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=status)
