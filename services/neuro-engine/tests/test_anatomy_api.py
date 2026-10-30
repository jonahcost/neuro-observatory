"""Anatomy asset HTTP API (mounted at /api/anatomy/v1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from anatomy_fixtures import write_freesurfer_subject
from fastapi.testclient import TestClient

from neuro_engine.anatomy.assets import prepare_asset
from neuro_engine.app import create_app
from neuro_engine.config import EngineSettings
from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.storage import DataRoot
from neuro_engine.datasets.subjects import resolve_subject

API = "/api/anatomy/v1"
ORIGIN = "http://localhost:4200"


@pytest.fixture
def data_root(tmp_path: Path) -> DataRoot:
    return DataRoot(tmp_path / "data")


@pytest.fixture
def client(data_root: DataRoot) -> TestClient:
    # No `with`: the acquisition lifespan is not needed for static asset routes.
    return TestClient(create_app(EngineSettings(data_dir=data_root.path)))


@pytest.fixture
def asset_id(data_root: DataRoot) -> str:
    write_freesurfer_subject(data_root.raw("fsaverage", get_dataset("fsaverage").version) / "fsaverage")
    return prepare_asset(data_root, resolve_subject(data_root, "fsaverage")).asset_id


def test_empty_catalog_when_nothing_is_prepared(client: TestClient) -> None:
    response = client.get(f"{API}/catalog")
    assert response.status_code == 200
    assert response.json() == {"type": "anatomy.catalog", "schemaVersion": 1, "defaultAssetId": None, "assets": []}


def test_catalog_manifest_and_buffers(client: TestClient, asset_id: str, data_root: DataRoot, anatomy_schema_validator) -> None:  # type: ignore[no-untyped-def]
    catalog = client.get(f"{API}/catalog").json()
    anatomy_schema_validator.validate(catalog)
    assert catalog["defaultAssetId"] == asset_id
    assert catalog["assets"][0]["anatomyKind"] == "template"

    manifest_response = client.get(f"{API}/assets/{asset_id}/manifest.json")
    assert manifest_response.status_code == 200
    assert manifest_response.headers["cache-control"] == "no-cache"
    manifest = manifest_response.json()
    anatomy_schema_validator.validate(manifest)

    ref = manifest["surfaces"][0]["positions"]
    buffer = client.get(f"{API}/assets/{asset_id}/files/{ref['file']}")
    assert buffer.status_code == 200
    assert buffer.headers["content-type"] == "application/octet-stream"
    assert "immutable" in buffer.headers["cache-control"]
    assert len(buffer.content) == ref["byteLength"]
    assert hashlib.sha256(buffer.content).hexdigest() == ref["sha256"]


@pytest.mark.parametrize(
    "path",
    [
        "/assets/{id}/files/manifest.json",
        "/assets/{id}/files/..%2Fmanifest.json",
        "/assets/{id}/files/%2e%2e",
        "/assets/{id}/files/unlisted.bin",
        "/assets/no-such-asset/manifest.json",
        "/assets/UPPER/manifest.json",
        "/assets/..%2F..%2Fraw/manifest.json",
    ],
)
def test_unlisted_files_and_traversal_are_not_found(client: TestClient, asset_id: str, data_root: DataRoot, path: str) -> None:
    (data_root.anatomy_assets / asset_id / "unlisted.bin").write_bytes(b"secret")
    response = client.get(API + path.format(id=asset_id))
    assert response.status_code == 404
    assert b"secret" not in response.content


def test_cors_allows_only_configured_origins_and_get(client: TestClient) -> None:
    allowed = client.get(f"{API}/catalog", headers={"origin": ORIGIN})
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    denied = client.get(f"{API}/catalog", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers
    preflight = client.options(
        f"{API}/catalog", headers={"origin": ORIGIN, "access-control-request-method": "DELETE"}
    )
    assert preflight.status_code == 400
    assert client.post(f"{API}/catalog").status_code == 405


def test_invalid_manifest_is_a_server_error(client: TestClient, asset_id: str, data_root: DataRoot) -> None:
    (data_root.anatomy_assets / asset_id / "manifest.json").write_text("{}")
    response = client.get(f"{API}/assets/{asset_id}/manifest.json")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "invalid-manifest"
    assert str(data_root.path) not in response.text
