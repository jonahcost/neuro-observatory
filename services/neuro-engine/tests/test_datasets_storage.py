from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from neuro_engine.datasets.catalog import DATASETS, LARGE_DOWNLOAD_BYTES, get_dataset
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import (
    ExpectedChecksum,
    checksum_from_openneuro_id,
    git_blob_sha1,
    md5_file,
    sha256_file,
)
from neuro_engine.datasets.provenance import (
    AcquiredFile,
    new_record,
    read_record,
    verify_record,
    write_record,
)
from neuro_engine.datasets.storage import (
    DataRoot,
    default_data_dir,
    ensure_outside_version_control,
    resolve_data_root,
)

# --- storage ---------------------------------------------------------------------------------


def test_default_data_dir_per_platform(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert default_data_dir({}, "darwin", home) == home / "Library" / "Application Support" / "NeuroObservatory"
    assert default_data_dir({"LOCALAPPDATA": str(tmp_path / "L")}, "win32", home) == tmp_path / "L" / "NeuroObservatory"
    assert default_data_dir({}, "linux", home) == home / ".local" / "share" / "neuro-observatory"
    assert default_data_dir({"XDG_DATA_HOME": str(tmp_path / "x")}, "linux", home) == tmp_path / "x" / "neuro-observatory"
    assert default_data_dir({"XDG_DATA_HOME": "relative"}, "linux", home) == home / ".local" / "share" / "neuro-observatory"


def test_resolve_data_root_precedence(tmp_path: Path) -> None:
    env = {"NEURO_ENGINE_DATA_DIR": str(tmp_path / "from-env")}
    assert resolve_data_root(tmp_path / "explicit", env).path == (tmp_path / "explicit").resolve()
    assert resolve_data_root(None, env).path == (tmp_path / "from-env").resolve()
    assert resolve_data_root(None, {"NEURO_ENGINE_DATA_DIR": "  "}).path == default_data_dir({}).resolve()


def test_layout_paths(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    assert root.raw("ds000248", "1.2.4") == tmp_path / "raw" / "ds000248" / "1.2.4"
    assert root.acquisition_record("ds000248", "1.2.4") == tmp_path / "raw" / "ds000248" / "1.2.4.acquisition.json"
    assert root.downloads("ixi", "v") == tmp_path / "downloads" / "ixi" / "v"
    assert root.anatomy_assets == tmp_path / "assets" / "anatomy"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_data_root_inside_a_git_tree_must_be_ignored(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored-data/\n")
    tracked = tmp_path / "data"
    tracked.mkdir()
    with pytest.raises(DatasetError) as info:
        ensure_outside_version_control(tracked)
    assert info.value.code == "data-root-in-repository"
    ignored = tmp_path / "ignored-data"
    ensure_outside_version_control(ignored)  # not created yet
    DataRoot(ignored).prepare_for_writing()
    assert ignored.is_dir()


def test_data_root_outside_git_is_accepted(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "plain" / "data")
    if any((p / ".git").exists() for p in (tmp_path, *tmp_path.parents)):
        pytest.skip("temporary directory is inside a git tree")
    root.prepare_for_writing()
    assert root.path.is_dir()


# --- integrity -------------------------------------------------------------------------------


def test_digests(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_bytes(b"hello\n")
    assert sha256_file(path) == hashlib.sha256(b"hello\n").hexdigest()
    assert md5_file(path) == "b1946ac92492d2347c6235b4d2611184"
    assert git_blob_sha1(path) == "ce013625030ba8dba906f756967f9e9ca394464a"  # `git hash-object`


def test_openneuro_ids_map_to_checksums(tmp_path: Path) -> None:
    md5 = checksum_from_openneuro_id("MD5E-s6--b1946ac92492d2347c6235b4d2611184.txt", 6)
    assert md5 == ExpectedChecksum("md5", "b1946ac92492d2347c6235b4d2611184")
    sha1 = checksum_from_openneuro_id("ce013625030ba8dba906f756967f9e9ca394464a", 6)
    assert sha1 == ExpectedChecksum("git-sha1", "ce013625030ba8dba906f756967f9e9ca394464a")
    path = tmp_path / "f"
    path.write_bytes(b"hello\n")
    assert md5 is not None and md5.matches(path)
    assert sha1 is not None and sha1.matches(path)
    assert checksum_from_openneuro_id("something-else", 6) is None


def test_annex_key_with_wrong_size_is_rejected() -> None:
    with pytest.raises(DatasetError):
        checksum_from_openneuro_id("MD5E-s7--b1946ac92492d2347c6235b4d2611184.txt", 6)


# --- catalog and provenance ------------------------------------------------------------------


def test_catalog_entries_are_complete_and_honest() -> None:
    assert set(DATASETS) == {"fsaverage", "ds000248", "ixi", "local"}
    ds = get_dataset("ds000248")
    assert ds.version == "1.2.4" and ds.acquisition.field_strength_tesla == 1.5
    assert ds.approx_download_bytes is not None and ds.approx_download_bytes < LARGE_DOWNLOAD_BYTES
    assert get_dataset("ixi").acquisition.field_strength_tesla == 3.0
    assert get_dataset("fsaverage").license.requires_acceptance
    for spec in DATASETS.values():
        assert spec.license.url.startswith("https://")
    with pytest.raises(DatasetError) as info:
        get_dataset("hcp")
    assert info.value.code == "unknown-dataset" and info.value.hint


def test_record_round_trip_and_verification(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    spec = get_dataset("ds000248")
    base = root.raw(spec.id, spec.version)
    (base / "sub-01").mkdir(parents=True)
    (base / "sub-01" / "a.txt").write_bytes(b"abc")
    record = new_record(spec, profile="anatomy")
    record.upsert_files([AcquiredFile(path="sub-01/a.txt", bytes=3, sha256=sha256_file(base / "sub-01" / "a.txt"))])
    write_record(root, record)
    loaded = read_record(root, spec.id, spec.version)
    assert loaded is not None and loaded.file_index()["sub-01/a.txt"].bytes == 3
    assert loaded.license_id == "CC0-1.0"
    assert verify_record(root, loaded) == []
    (base / "sub-01" / "a.txt").write_bytes(b"abd")
    assert verify_record(root, loaded) == ["sub-01/a.txt: SHA-256 differs from the recorded value"]
    (base / "sub-01" / "a.txt").unlink()
    assert verify_record(root, loaded) == ["sub-01/a.txt: missing"]


def test_corrupt_record_is_reported(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    path = root.acquisition_record("ixi", get_dataset("ixi").version)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    with pytest.raises(DatasetError) as info:
        read_record(root, "ixi", get_dataset("ixi").version)
    assert info.value.code == "corrupt-provenance"


def test_record_identity_must_match_requested_dataset(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    path = root.acquisition_record("ixi", get_dataset("ixi").version)
    path.parent.mkdir(parents=True)
    record = new_record(get_dataset("ds000248"))
    path.write_text(record.model_dump_json())
    with pytest.raises(DatasetError) as info:
        read_record(root, "ixi", get_dataset("ixi").version)
    assert info.value.code == "corrupt-provenance"


def test_concurrent_record_updates_are_merged_under_one_lock(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    spec = get_dataset("ixi")
    barrier = threading.Barrier(2)

    def update(name: str) -> None:
        record = new_record(spec)
        record.upsert_files([AcquiredFile(path=name, bytes=1, sha256="0" * 64)])
        barrier.wait()
        write_record(root, record)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, ("a.nii.gz", "b.nii.gz")))
    record = read_record(root, spec.id, spec.version)
    assert record is not None and set(record.file_index()) == {"a.nii.gz", "b.nii.gz"}


def test_record_paths_must_be_relative() -> None:
    with pytest.raises(ValueError):
        AcquiredFile(path="/etc/passwd", bytes=1, sha256="0" * 64)
