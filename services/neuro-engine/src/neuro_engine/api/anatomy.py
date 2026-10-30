"""Read-only HTTP access to prepared anatomy assets, mounted at /api/anatomy/v1.

Only files listed in an asset's manifest are served. Handlers are sync so file
I/O runs in the threadpool, away from the acquisition event loop.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from neuro_engine.anatomy.assets import AssetStore
from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.config import EngineSettings
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.storage import resolve_data_root
from neuro_engine.protocol import anatomy_v1

MOUNT_PATH = "/api/anatomy/v1"
_NOT_FOUND = {"unknown-asset", "unknown-file", "invalid-asset-id"}
IMMUTABLE = "private, max-age=31536000, immutable"


def create_anatomy_app(settings: EngineSettings) -> FastAPI:
    app = FastAPI(title="Neuro Observatory anatomy assets", openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(settings.allowed_origins),
        allow_methods=["GET"],
        allow_headers=[],
        allow_credentials=False,
    )

    def store() -> AssetStore:
        return AssetStore(resolve_data_root(settings.data_dir))

    @app.exception_handler(AnatomyError)
    def anatomy_error(_: Request, exc: AnatomyError) -> JSONResponse:
        status = 404 if exc.code in _NOT_FOUND else 500
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=status)

    @app.exception_handler(DatasetError)
    def dataset_error(_: Request, exc: DatasetError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=503)

    @app.get("/catalog")
    def catalog() -> dict[str, Any]:
        return anatomy_v1.to_wire_dict(store().catalog())

    @app.get("/assets/{asset_id}/manifest.json")
    def manifest(asset_id: str) -> Response:
        assets = store()
        assets.manifest(asset_id)
        return Response(assets.manifest_bytes(asset_id), media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/assets/{asset_id}/files/{file_name}")
    def buffer(asset_id: str, file_name: str) -> FileResponse:
        path = store().buffer_path(asset_id, file_name)
        return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": IMMUTABLE})

    return app
