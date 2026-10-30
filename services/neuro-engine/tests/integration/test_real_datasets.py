"""Checks against real downloaded datasets. Opt-in: `nx run neuro-engine:test-integration`.

Each test skips (with the command to run) when its dataset is absent.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from neuro_engine.anatomy.assets import AssetStore, prepare_asset
from neuro_engine.anatomy.volumes import check_mri
from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.ixi import verify_gzip
from neuro_engine.datasets.provenance import read_record, verify_record, write_record
from neuro_engine.datasets.storage import ENV_DATA_DIR, DataRoot, resolve_data_root
from neuro_engine.datasets.subjects import SubjectSource, check_subject, resolve_subject

pytestmark = pytest.mark.integration

FSAVERAGE_VERTICES = 163_842  # ico7


# Defined here, not in a tests/integration/conftest.py: unit tests import helpers
# with `from conftest import ...`, which a second conftest module would shadow.
@pytest.fixture(scope="module")
def data_root() -> DataRoot:
    if not os.environ.get(ENV_DATA_DIR):
        pytest.skip(f"set {ENV_DATA_DIR} to a data root with fetched datasets")
    return resolve_data_root()


def subject_or_skip(root: DataRoot, key: str, fetch: str) -> SubjectSource:
    try:
        return resolve_subject(root, key)
    except DatasetError:
        pytest.skip(f"{key} not present; run: neuro-engine datasets fetch {fetch}")


def assert_record_verifies(root: DataRoot, dataset_id: str) -> None:
    spec = get_dataset(dataset_id)
    record = read_record(root, spec.id, spec.version)
    assert record is not None and record.files
    assert verify_record(root, record) == []


def isolated_dataset_root(source: DataRoot, dataset_id: str, destination: Path) -> DataRoot:
    """Clone public test inputs into a fresh root so preparation cannot reuse a cached asset."""
    spec = get_dataset(dataset_id)
    record = read_record(source, spec.id, spec.version)
    assert record is not None
    root = DataRoot(destination)
    source_base = source.raw(spec.id, spec.version)
    target_base = root.raw(spec.id, spec.version)
    for entry in record.files:
        src = source_base / entry.path
        dst = target_base / entry.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    write_record(root, record.model_copy(deep=True))
    return root


def enclosed_volume_cm3(positions: np.ndarray, triangles: np.ndarray) -> float:
    """Signed volume of a closed mesh; positive when triangles wind counter-clockwise seen from outside."""
    v = positions.astype(np.float64)[triangles]
    return float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0 / 1000.0)


# Plausible adult per-hemisphere volumes (cm³) enclosed by each surface; a sign or
# unit error (metres, flipped winding) falls far outside these.
ENCLOSED_VOLUME_CM3 = {"pial": (300.0, 800.0), "white": (150.0, 500.0)}


def assert_outward_closed_surfaces(store: AssetStore, asset_id: str) -> None:
    for hemisphere in ("lh", "rh"):
        for surface, (low, high) in ENCLOSED_VOLUME_CM3.items():
            volume = enclosed_volume_cm3(*store.load_mesh(asset_id, hemisphere, surface))
            assert low < volume < high, f"{hemisphere}.{surface}: {volume:.1f} cm³"


def test_fsaverage_end_to_end(data_root: DataRoot, tmp_path: Path) -> None:
    subject_or_skip(data_root, "fsaverage", "fsaverage --accept-license")
    assert_record_verifies(data_root, "fsaverage")
    isolated = isolated_dataset_root(data_root, "fsaverage", tmp_path / "fresh-fsaverage")
    subject = resolve_subject(isolated, "fsaverage")
    assert not [f for f in check_subject(subject) if f.level == "error"]
    prepared = prepare_asset(isolated, subject)
    assert prepared.created
    store = AssetStore(isolated)
    assert store.verify(prepared.asset_id) == []
    asset = store.manifest(prepared.asset_id)
    assert asset.anatomy_kind == "template"
    assert {(s.hemisphere, s.surface) for s in asset.surfaces} == {
        (h, k) for h in ("lh", "rh") for k in ("pial", "white", "inflated")
    }
    assert all(s.vertex_count == FSAVERAGE_VERTICES for s in asset.surfaces)
    mni = next(t for t in asset.transforms if t.to == "mni305-ras")
    assert mni.matrix == [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    lh, _ = store.load_mesh(prepared.asset_id, "lh", "pial")
    rh, _ = store.load_mesh(prepared.asset_id, "rh", "pial")
    # Hemispheres lie on their own side of the midline; head-sized extents in mm (not metres).
    assert np.median(lh[:, 0]) < 0 < np.median(rh[:, 0])
    extent = np.vstack([lh, rh]).max(axis=0) - np.vstack([lh, rh]).min(axis=0)
    assert np.all((100 < extent) & (extent < 220))
    assert_outward_closed_surfaces(store, prepared.asset_id)
    assert {p.atlas for p in asset.parcellations} >= {"aparc", "aparc.a2009s"}


def test_ds000248_sub01_end_to_end(data_root: DataRoot, tmp_path: Path) -> None:
    subject_or_skip(data_root, "ds000248/sub-01", "ds000248")
    assert_record_verifies(data_root, "ds000248")
    isolated = isolated_dataset_root(data_root, "ds000248", tmp_path / "fresh-ds000248")
    subject = resolve_subject(isolated, "ds000248/sub-01")
    findings = check_subject(subject)
    assert not [f for f in findings if f.level == "error"], findings
    codes = {f.code for f in findings}
    assert "rawavg-matches-t1" in codes and "landmarks" in codes
    prepared = prepare_asset(isolated, subject)
    assert prepared.created
    store = AssetStore(isolated)
    assert store.verify(prepared.asset_id) == []
    asset = store.manifest(prepared.asset_id)
    assert asset.anatomy_kind == "reference-subject"
    assert asset.acquisition.field_strength_tesla == 1.5 and asset.acquisition.source == "dataset-readme"
    scanner = next(t for t in asset.transforms if t.to == "scanner-ras")
    assert "orig.mgz" in scanner.source  # cross-checked against the surfaces' c_ras
    assert {p.atlas for p in asset.parcellations} >= {"aparc", "aparc.a2009s", "aparc.dktatlas"}
    assert {(p.atlas, p.hemisphere) for p in asset.parcellations if p.atlas == "aparc"} == {
        ("aparc", "lh"),
        ("aparc", "rh"),
    }
    assert all(len(p.labels) > 30 for p in asset.parcellations)
    assert_outward_closed_surfaces(store, prepared.asset_id)


def test_ds000248_eeg_metadata(data_root: DataRoot) -> None:
    pytest.importorskip("mne_bids")
    from neuro_engine.datasets.eeg import inspect_eeg

    subject = subject_or_skip(data_root, "ds000248/sub-01", "ds000248")
    result = inspect_eeg(subject)
    assert result.eeg_channels == 60
    assert result.sampling_rate_hz == pytest.approx(600.615, abs=1e-3)
    assert result.digitized_eeg_positions >= 60
    assert set(result.fiducials) == {"LPA", "NASION", "RPA"}
    assert result.head_shape_points == 78
    assert result.source_localization_ready is False
    assert result.missing_for_source_localization


def test_ixi_hh_t1(data_root: DataRoot) -> None:
    subject = subject_or_skip(data_root, "ixi/IXI012-HH-1211", "ixi --subject IXI012-HH-1211 --accept-license")
    assert_record_verifies(data_root, "ixi")
    assert subject.t1 is not None
    verify_gzip(subject.t1)
    check = check_mri(subject.t1)
    assert check.ok
    assert subject.acquisition.field_strength_tesla == 3.0
    assert len(check.info.shape) == 3 and all(0.5 < v < 2.0 for v in check.info.voxel_size_mm)
