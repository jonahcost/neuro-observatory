from __future__ import annotations

import json
import shutil
from pathlib import Path

import nibabel as nib
import pytest
from anatomy_fixtures import record_dataset_files, write_freesurfer_subject, write_t1

from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.local import import_freesurfer, import_mri
from neuro_engine.datasets.provenance import read_record
from neuro_engine.datasets.storage import DataRoot
from neuro_engine.datasets.subjects import check_subject, list_subjects, resolve_subject

DS = get_dataset("ds000248")


def write_ds000248(root: DataRoot, *, rawavg_matches: bool = True, landmark: list[float] | None = None) -> Path:
    base = root.raw(DS.id, DS.version)
    (base / "sub-01" / "anat").mkdir(parents=True)
    (base / "dataset_description.json").write_text('{"Name": "synthetic", "BIDSVersion": "1.9.0"}')
    (base / "participants.tsv").write_bytes("\ufeffparticipant_id\tage\nsub-01\tn/a\n".encode())
    t1 = write_t1(base / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    (base / "sub-01" / "anat" / "sub-01_T1w.json").write_text(
        json.dumps({"AnatomicalLandmarkCoordinates": {"NAS": landmark or [12, 25, 10], "LPA": [2, 14, 8], "RPA": [22, 14, 8]}})
    )
    (base / "sub-01" / "meg").mkdir()
    (base / "sub-01" / "meg" / "sub-01_task-audiovisual_run-01_meg.json").write_text(
        json.dumps({"EEGChannelCount": 60, "SamplingFrequency": 600.614990234375})
    )
    fs = write_freesurfer_subject(base / "derivatives" / "freesurfer" / "subjects" / "sub-01")
    image = nib.load(t1)
    rawavg = image if rawavg_matches else nib.Nifti1Image(image.get_fdata(), image.affine * [[1], [1], [1.1], [1]])
    nib.save(nib.MGHImage(rawavg.get_fdata().astype("float32"), rawavg.affine), fs / "mri" / "rawavg.mgz")
    return base


def codes(findings) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.code for f in findings}


def test_subjects_are_discovered_across_datasets(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    assert list_subjects(root) == []
    write_freesurfer_subject(root.raw("fsaverage", get_dataset("fsaverage").version) / "fsaverage")
    write_ds000248(root)
    write_t1(root.raw("ixi", get_dataset("ixi").version) / "IXI012-HH-1211-T1.nii.gz")
    for dataset_id in ("fsaverage", "ds000248", "ixi"):
        record_dataset_files(root, dataset_id)
    keys = {s.key: s for s in list_subjects(root)}
    assert list(keys) == ["fsaverage", "ds000248/sub-01", "ixi/IXI012-HH-1211"]
    assert keys["fsaverage"].spec.anatomy_kind == "template" and keys["fsaverage"].has_surfaces
    assert keys["ds000248/sub-01"].acquisition.field_strength_tesla == 1.5
    ixi = keys["ixi/IXI012-HH-1211"]
    assert ixi.freesurfer_dir is None and not ixi.has_surfaces
    assert ixi.acquisition.field_strength_tesla == 3.0 and ixi.acquisition.source == "site-documentation"
    summary = keys["ds000248/sub-01"].summary()
    assert summary["t1"] == "raw/ds000248/1.2.4/sub-01/anat/sub-01_T1w.nii.gz"
    with pytest.raises(DatasetError) as info:
        resolve_subject(root, "ds000248/sub-02")
    assert info.value.code == "unknown-subject"


def test_ds000248_consistency_checks_pass(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    write_ds000248(root)
    record_dataset_files(root, "ds000248")
    findings = check_subject(resolve_subject(root, "ds000248/sub-01"))
    assert not [f for f in findings if f.level == "error"]
    assert {"rawavg-matches-t1", "landmarks", "eeg-recording"} <= codes(findings)
    eeg = next(f for f in findings if f.code == "eeg-recording")
    assert "60 EEG channels" in eeg.message


def test_ds000248_inconsistencies_are_reported(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    base = write_ds000248(root, rawavg_matches=False, landmark=[500, 0, 0])
    (base / "participants.tsv").write_text("participant_id\nsub-02\n")
    (base / "sub-01" / "anat" / "stray.txt").write_text("x")
    record_dataset_files(root, "ds000248")
    findings = check_subject(resolve_subject(root, "ds000248/sub-01"))
    assert {"rawavg-differs", "landmark-outside-volume", "not-in-participants", "bids-entity-mismatch"} <= codes(findings)


def test_subject_without_reconstruction_is_flagged(tmp_path: Path) -> None:
    root = DataRoot(tmp_path)
    write_t1(root.raw("ixi", get_dataset("ixi").version) / "IXI012-HH-1211-T1.nii.gz")
    record_dataset_files(root, "ixi")
    findings = check_subject(resolve_subject(root, "ixi/IXI012-HH-1211"))
    assert "no-reconstruction" in codes(findings)


def test_local_import_of_t1_and_freesurfer(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "data")
    private = tmp_path / "Jane Doe MRI" / "jane_doe_t1.nii.gz"
    write_t1(private, shape=(40, 40, 40))
    import_mri(root, private, "me", field_strength_tesla=3.0, sequence="MPRAGE", scanner="Siemens Prisma")
    fs_source = write_freesurfer_subject(tmp_path / "recon" / "jane")
    (fs_source / "mri" / "brainmask.mgz").write_bytes(b"not copied")
    import_freesurfer(
        root,
        fs_source,
        "me",
        tool_name="FreeSurfer",
        tool_version="test",
        command_summary="recon-all test",
        qc_status="passed",
    )

    subject = resolve_subject(root, "local/me")
    assert subject.spec.anatomy_kind == "personal"
    assert subject.t1 is not None and subject.t1.name == "T1w.nii.gz"
    assert subject.has_surfaces
    assert (subject.acquisition.field_strength_tesla, subject.acquisition.source) == (3.0, "user-declared")
    assert not (subject.freesurfer_dir / "mri" / "brainmask.mgz").exists()  # type: ignore[operator]

    record_text = root.acquisition_record("local", "1").read_text()
    assert "Jane" not in record_text and "jane" not in record_text and str(tmp_path) not in record_text
    record = read_record(root, "local", "1")
    assert record is not None and record.declared_acquisition["me"].sequence == "MPRAGE"

    import_mri(root, private, "me")  # identical re-import is a no-op
    other = write_t1(tmp_path / "other.nii.gz", shape=(30, 30, 30))
    with pytest.raises(DatasetError) as info:
        import_mri(root, other, "me")
    assert info.value.code == "existing-file-mismatch"


@pytest.mark.parametrize("label", ["Jane", "a b", "-x", "", "x" * 33, "../me"])
def test_invalid_local_labels(tmp_path: Path, label: str) -> None:
    with pytest.raises(DatasetError) as info:
        import_mri(DataRoot(tmp_path), tmp_path / "t1.nii.gz", label)
    assert info.value.code == "invalid-subject-label"


def test_local_imports_reject_bad_inputs(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "data")
    with pytest.raises(DatasetError) as volume:
        import_mri(root, write_t1(tmp_path / "flat.nii.gz", constant=True), "me")
    assert volume.value.code == "invalid-volume"
    with pytest.raises(DatasetError) as strength:
        import_mri(root, write_t1(tmp_path / "t1.nii.gz"), "me", field_strength_tesla=0)
    assert strength.value.code == "invalid-field-strength"
    import_mri(root, write_t1(tmp_path / "source.nii.gz"), "me")
    fs = write_freesurfer_subject(tmp_path / "recon")
    (fs / "surf" / "rh.inflated").unlink()
    with pytest.raises(DatasetError) as incomplete:
        import_freesurfer(
            root,
            fs,
            "me",
            tool_name="FreeSurfer",
            tool_version="test",
            command_summary="recon-all test",
            qc_status="passed",
        )
    assert incomplete.value.code == "incomplete-freesurfer-subject"
    shutil.rmtree(fs)
    fs = write_freesurfer_subject(tmp_path / "recon")
    (fs / "surf" / "lh.white").write_bytes(b"garbage")
    with pytest.raises(DatasetError) as corrupt:
        import_freesurfer(
            root,
            fs,
            "me",
            tool_name="FreeSurfer",
            tool_version="test",
            command_summary="recon-all test",
            qc_status="passed",
        )
    assert corrupt.value.code == "invalid-surface"


def test_reconstruction_cannot_reseal_a_modified_source_t1(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "data")
    imported = import_mri(root, write_t1(tmp_path / "t1.nii.gz"), "me")
    imported.write_bytes(imported.read_bytes() + b"\0")
    source = write_freesurfer_subject(tmp_path / "recon")
    with pytest.raises(DatasetError) as info:
        import_freesurfer(
            root,
            source,
            "me",
            tool_name="FreeSurfer",
            tool_version="test",
            command_summary="recon-all test",
            qc_status="passed",
        )
    assert info.value.code == "source-provenance-mismatch"
    assert not (root.raw("local", "1") / "freesurfer" / "me").exists()
