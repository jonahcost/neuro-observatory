from __future__ import annotations

import os
from pathlib import Path

import pytest
from anatomy_fixtures import nifti_gz_bytes, tar_bytes
from fake_http import FakeServer

from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.fsaverage import FSAVERAGE_ANATOMY_FILES, fetch_fsaverage
from neuro_engine.datasets.ixi import (
    IXI_T1_TAR_URL,
    fetch_ixi_subject,
    import_ixi_file,
    locate_tar_member,
    parse_ixi_t1_name,
)
from neuro_engine.datasets.provenance import read_record
from neuro_engine.datasets.storage import DataRoot

IXI_VERSION = get_dataset("ixi").version
HH = "IXI012-HH-1211-T1.nii.gz"
GUYS = "IXI002-Guys-0828-T1.nii.gz"


@pytest.fixture(scope="module")
def archive() -> tuple[bytes, bytes]:
    hh = nifti_gz_bytes(shape=(30, 32, 28))
    return tar_bytes([(GUYS, nifti_gz_bytes(shape=(20, 20, 20))), (HH, hh), ("IXI013-HH-1212-T1.nii.gz", b"x" * 700)]), hh


# --- IXI -------------------------------------------------------------------------------------


def test_ixi_names_map_to_documented_sites() -> None:
    hh = parse_ixi_t1_name(HH)
    assert (hh.subject_id, hh.site, hh.acquisition.field_strength_tesla) == ("IXI012-HH-1211", "HH", 3.0)
    assert parse_ixi_t1_name(GUYS).acquisition.field_strength_tesla == 1.5
    for bad in ("IXI012-HH-1211-T2.nii.gz", "IXI012-XX-1211-T1.nii.gz", "../IXI012-HH-1211-T1.nii.gz"):
        with pytest.raises(DatasetError):
            parse_ixi_t1_name(bad)


def test_tar_member_is_located_from_headers_only(archive: tuple[bytes, bytes]) -> None:
    data, hh = archive
    reads: list[tuple[int, int]] = []

    def read(start: int, length: int) -> bytes:
        reads.append((start, length))
        return data[start : start + length]

    member = locate_tar_member(HH, read)
    assert data[member.data_offset : member.data_offset + member.size] == hh
    assert all(length == 512 for _, length in reads) and len(reads) == 2
    with pytest.raises(DatasetError) as info:
        locate_tar_member("IXI999-HH-9999-T1.nii.gz", read)
    assert info.value.code == "member-not-found"


def test_corrupt_tar_header_is_rejected(archive: tuple[bytes, bytes]) -> None:
    data = bytearray(archive[0])
    data[100] ^= 0xFF
    with pytest.raises(DatasetError) as info:
        locate_tar_member(HH, lambda s, n: bytes(data[s : s + n]))
    assert info.value.code == "corrupt-archive"


def test_fetch_downloads_one_member_verifies_and_records(tmp_path: Path, archive: tuple[bytes, bytes]) -> None:
    data, hh = archive
    server = FakeServer({IXI_T1_TAR_URL: data})
    root = DataRoot(tmp_path)
    with pytest.raises(DatasetError) as refused:
        fetch_ixi_subject(root, "IXI012-HH-1211", accept_license=False, opener=server)
    assert refused.value.code == "license-not-accepted" and server.requests == []

    path = fetch_ixi_subject(root, "IXI012-HH-1211", accept_license=True, opener=server)
    assert path == root.raw("ixi", IXI_VERSION) / HH
    assert path.read_bytes() == hh
    assert all(r is not None and r.startswith("bytes=") for _, r in server.requests)
    received = sum(int(r.split("-")[1]) - int(r.split("=")[1].split("-")[0]) + 1 for _, r in server.requests if r)
    assert received == 2 * 512 + len(hh)

    record = read_record(root, "ixi", IXI_VERSION)
    assert record is not None and record.license_accepted_at_utc is not None
    entry = record.file_index()[HH]
    assert entry.upstream_checksum is not None and "gzip-crc32-verified" in entry.upstream_checksum


def test_member_that_is_not_valid_gzip_is_deleted(tmp_path: Path, archive: tuple[bytes, bytes]) -> None:
    root = DataRoot(tmp_path)
    with pytest.raises(DatasetError) as info:
        fetch_ixi_subject(root, "IXI013-HH-1212", accept_license=True, opener=FakeServer({IXI_T1_TAR_URL: archive[0]}))
    assert info.value.code == "corrupt-file"
    assert not (root.raw("ixi", IXI_VERSION) / "IXI013-HH-1212-T1.nii.gz").exists()


def test_local_import_validates_and_refuses_overwrite(tmp_path: Path, archive: tuple[bytes, bytes]) -> None:
    root = DataRoot(tmp_path / "data")
    source = tmp_path / "downloads" / HH
    source.parent.mkdir()
    source.write_bytes(archive[1])
    imported = import_ixi_file(root, source, accept_license=True)
    assert imported.read_bytes() == archive[1]
    assert import_ixi_file(root, source, accept_license=True) == imported
    other = tmp_path / "other" / HH
    other.parent.mkdir()
    other.write_bytes(nifti_gz_bytes(shape=(22, 22, 22)))
    with pytest.raises(DatasetError) as info:
        import_ixi_file(root, other, accept_license=True)
    assert info.value.code == "existing-file-mismatch"
    truncated = tmp_path / "bad" / HH
    truncated.parent.mkdir()
    truncated.write_bytes(archive[1][:-20])
    with pytest.raises(DatasetError):
        import_ixi_file(DataRoot(tmp_path / "data2"), truncated, accept_license=True)


def test_guys_subject_records_its_field_strength(tmp_path: Path, archive: tuple[bytes, bytes]) -> None:
    root = DataRoot(tmp_path)
    fetch_ixi_subject(root, "IXI002-Guys-0828", accept_license=True, opener=FakeServer({IXI_T1_TAR_URL: archive[0]}))
    record = read_record(root, "ixi", IXI_VERSION)
    assert record is not None and any("1.5 T" in note for note in record.notes)


# --- fsaverage -------------------------------------------------------------------------------


def fake_mne_fetch(subjects_dir: Path) -> Path:
    assert os.environ["SUBJECTS_DIR"] == str(subjects_dir)
    for relative in FSAVERAGE_ANATOMY_FILES:
        path = subjects_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    return subjects_dir / "fsaverage"


def test_fsaverage_requires_license_acceptance(tmp_path: Path) -> None:
    with pytest.raises(DatasetError) as info:
        fetch_fsaverage(DataRoot(tmp_path), accept_license=False, fetch=fake_mne_fetch)
    assert info.value.code == "license-not-accepted" and "--accept-license" in (info.value.hint or "")


def test_fsaverage_fetch_records_files_and_restores_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBJECTS_DIR", "/previous")
    root = DataRoot(tmp_path)
    path = fetch_fsaverage(root, accept_license=True, fetch=fake_mne_fetch)
    assert path == root.raw("fsaverage", get_dataset("fsaverage").version) / "fsaverage"
    assert os.environ["SUBJECTS_DIR"] == "/previous"
    record = read_record(root, "fsaverage", get_dataset("fsaverage").version)
    assert record is not None and len(record.files) == len(FSAVERAGE_ANATOMY_FILES)
    assert record.license_id == "LicenseRef-FreeSurfer-1.0" and record.license_accepted_at_utc


def test_fsaverage_incomplete_or_failed_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBJECTS_DIR", raising=False)

    def partial(subjects_dir: Path) -> Path:
        (subjects_dir / "fsaverage").mkdir(parents=True)
        return subjects_dir / "fsaverage"

    with pytest.raises(DatasetError) as incomplete:
        fetch_fsaverage(DataRoot(tmp_path), accept_license=True, fetch=partial)
    assert incomplete.value.code == "incomplete-dataset"
    assert "SUBJECTS_DIR" not in os.environ

    def broken(_: Path) -> Path:
        raise ConnectionError("offline")

    with pytest.raises(DatasetError) as failed:
        fetch_fsaverage(DataRoot(tmp_path / "b"), accept_license=True, fetch=broken)
    assert failed.value.code == "fetch-failed"
