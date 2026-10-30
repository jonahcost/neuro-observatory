from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from anatomy_fixtures import (
    DEFAULT_CRAS,
    surface_vertices,
    write_freesurfer_subject,
    write_surface,
)

from neuro_engine.anatomy.assets import AssetStore, prepare_asset
from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.storage import DataRoot
from neuro_engine.datasets.subjects import resolve_subject


def fixed_clock() -> str:
    return "2026-10-30T12:00:00Z"


@pytest.fixture
def root(tmp_path: Path) -> DataRoot:
    return DataRoot(tmp_path / "data")


def fsaverage_dir(root: DataRoot) -> Path:
    spec = get_dataset("fsaverage")
    return root.raw(spec.id, spec.version) / "fsaverage"


def local_fs_dir(root: DataRoot, label: str = "me") -> Path:
    return root.raw("local", "1") / "freesurfer" / label


def test_prepare_writes_a_contract_valid_asset_preserving_coordinates(root: DataRoot, anatomy_schema_validator) -> None:  # type: ignore[no-untyped-def]
    write_freesurfer_subject(local_fs_dir(root), atlases=("aparc", "aparc.a2009s"))
    subject = resolve_subject(root, "local/me")
    prepared = prepare_asset(root, subject, clock=fixed_clock)
    assert prepared.created
    assert prepared.asset_id.startswith("local-me-")

    manifest = json.loads((prepared.path / "manifest.json").read_text())
    anatomy_schema_validator.validate(manifest)
    assert manifest["anatomyKind"] == "personal"
    assert manifest["coordinateFrame"] == "freesurfer-surface-ras"
    assert manifest["units"] == "mm"
    assert manifest["acquisition"]["source"] == "user-declared"
    assert [(s["hemisphere"], s["surface"]) for s in manifest["surfaces"]] == [
        ("lh", "pial"), ("lh", "white"), ("lh", "inflated"), ("rh", "pial"), ("rh", "white"), ("rh", "inflated"),
    ]  # fmt: skip
    assert sorted({(p["hemisphere"], p["atlas"]) for p in manifest["parcellations"]}) == [
        ("lh", "aparc"), ("lh", "aparc.a2009s"), ("rh", "aparc"), ("rh", "aparc.a2009s"),
    ]  # fmt: skip
    assert all(not Path(s["path"]).is_absolute() and s["path"].startswith("raw/local/1/") for s in manifest["provenance"]["sources"])

    (transform,) = manifest["transforms"]
    assert transform["to"] == "scanner-ras" and "orig.mgz" in transform["source"]
    np.testing.assert_allclose(transform["matrix"][3::4][:3], DEFAULT_CRAS, atol=1e-6)

    positions, faces = AssetStore(root).load_mesh(prepared.asset_id, "rh", "inflated")
    expected_vertices, expected_faces = surface_vertices("rh", "inflated")
    np.testing.assert_array_equal(positions.astype(np.float64), expected_vertices)  # no rescaling or recentring
    np.testing.assert_array_equal(faces, expected_faces)


def test_prepare_is_idempotent_and_content_addressed(root: DataRoot) -> None:
    write_freesurfer_subject(local_fs_dir(root))
    subject = resolve_subject(root, "local/me")
    first = prepare_asset(root, subject, clock=fixed_clock)
    second = prepare_asset(root, subject, clock=lambda: "2030-01-01T00:00:00Z")
    assert second.asset_id == first.asset_id and not second.created
    only_pial = prepare_asset(root, subject, surfaces=["pial"], atlases=[])
    assert only_pial.asset_id != first.asset_id
    assert not list(AssetStore(root).path.glob(".staging-*"))


def test_changed_source_gives_a_new_asset_id(root: DataRoot) -> None:
    fs = write_freesurfer_subject(local_fs_dir(root))
    first = prepare_asset(root, resolve_subject(root, "local/me")).asset_id
    vertices, faces = surface_vertices("lh", "pial")
    write_surface(fs / "surf" / "lh.pial", vertices + 0.5, faces)
    assert prepare_asset(root, resolve_subject(root, "local/me")).asset_id != first


def test_fsaverage_asset_is_template_with_mni305_transform_and_default(root: DataRoot) -> None:
    write_freesurfer_subject(fsaverage_dir(root))
    write_freesurfer_subject(local_fs_dir(root))
    template = prepare_asset(root, resolve_subject(root, "fsaverage"), clock=fixed_clock)
    prepare_asset(root, resolve_subject(root, "local/me"), clock=fixed_clock)
    manifest = AssetStore(root).manifest(template.asset_id)
    assert manifest.anatomy_kind == "template"
    assert manifest.license.id == "LicenseRef-FreeSurfer-1.0"
    assert {t.to for t in manifest.transforms} == {"scanner-ras", "mni305-ras"}
    catalog = AssetStore(root).catalog()
    assert catalog.default_asset_id == template.asset_id
    assert len(catalog.assets) == 2


def test_subject_without_surfaces_cannot_be_prepared(root: DataRoot) -> None:
    write_freesurfer_subject(local_fs_dir(root), kinds=("pial", "white"))
    with pytest.raises(AnatomyError) as info:
        prepare_asset(root, resolve_subject(root, "local/me"))
    assert info.value.code == "no-surfaces"


def test_surfaces_from_different_reconstructions_are_rejected(root: DataRoot) -> None:
    fs = write_freesurfer_subject(local_fs_dir(root), orig=False)
    vertices, faces = surface_vertices("rh", "white")
    write_surface(fs / "surf" / "rh.white", vertices, faces, cras=(9.0, 9.0, 9.0))
    with pytest.raises(AnatomyError) as info:
        prepare_asset(root, resolve_subject(root, "local/me"))
    assert info.value.code == "inconsistent-transform"


def test_explicit_missing_atlas_is_an_error(root: DataRoot) -> None:
    write_freesurfer_subject(local_fs_dir(root), atlases=("aparc",))
    with pytest.raises(AnatomyError) as info:
        prepare_asset(root, resolve_subject(root, "local/me"), atlases=["aparc.DKTatlas"])
    assert info.value.code == "missing-file"
    with pytest.raises(AnatomyError) as unknown:
        prepare_asset(root, resolve_subject(root, "local/me"), atlases=["yeo7"])
    assert unknown.value.code == "unknown-atlas"


def test_tampered_buffer_fails_verification_and_reprepare(root: DataRoot) -> None:
    write_freesurfer_subject(local_fs_dir(root))
    subject = resolve_subject(root, "local/me")
    prepared = prepare_asset(root, subject)
    store = AssetStore(root)
    assert store.verify(prepared.asset_id) == []
    target = prepared.path / "lh.pial.positions.f32"
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))
    assert any("SHA-256" in p for p in store.verify(prepared.asset_id))
    with pytest.raises(AnatomyError) as info:
        prepare_asset(root, subject)
    assert info.value.code == "corrupt-asset"
    with pytest.raises(AnatomyError):
        store.load_mesh(prepared.asset_id, "lh", "pial")


def test_store_serves_only_manifest_listed_files(root: DataRoot) -> None:
    write_freesurfer_subject(local_fs_dir(root))
    prepared = prepare_asset(root, resolve_subject(root, "local/me"))
    store = AssetStore(root)
    assert store.buffer_path(prepared.asset_id, "lh.pial.indices.u32").is_file()
    (prepared.path / "extra.bin").write_bytes(b"x")
    for name in ("manifest.json", "extra.bin", "../manifest.json", "lh.pial.indices.u32/.."):
        with pytest.raises(AnatomyError) as info:
            store.buffer_path(prepared.asset_id, name)
        assert info.value.code == "unknown-file"
    for bad_id in ("../data", "UPPER", ""):
        with pytest.raises(AnatomyError):
            store.manifest(bad_id)


def test_invalid_manifest_is_reported_not_listed(root: DataRoot) -> None:
    write_freesurfer_subject(local_fs_dir(root))
    prepared = prepare_asset(root, resolve_subject(root, "local/me"))
    manifest = prepared.path / "manifest.json"
    document = json.loads(manifest.read_text())
    document["units"] = "m"
    manifest.write_text(json.dumps(document))
    assets, problems = AssetStore(root).assets()
    assert assets == [] and len(problems) == 1
    assert AssetStore(root).catalog().default_asset_id is None


def test_empty_store_has_empty_catalog(root: DataRoot) -> None:
    catalog = AssetStore(root).catalog()
    assert catalog.assets == [] and catalog.default_asset_id is None
