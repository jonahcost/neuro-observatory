from __future__ import annotations

import json
from pathlib import Path

import pytest
from anatomy_fixtures import write_freesurfer_subject, write_t1

from neuro_engine.cli import main
from neuro_engine.datasets.catalog import get_dataset


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_datasets_list_and_info(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--data-dir", str(tmp_path), "--json", "datasets", "list")
    assert code == 0
    assert [d["id"] for d in json.loads(out)["datasets"]] == ["fsaverage", "ds000248", "ixi", "local"]
    code, out, _ = run(capsys, "--data-dir", str(tmp_path), "datasets", "info", "ds000248")
    assert code == 0 and "CC0" in out and "1.5 T" in out and "10.18112/openneuro.ds000248.v1.2.4" in out


def test_errors_exit_1_with_hint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "--data-dir", str(tmp_path), "datasets", "info", "nope")
    assert code == 1 and "error [unknown-dataset]" in err and "hint:" in err
    code, _, err = run(capsys, "--data-dir", str(tmp_path), "datasets", "fetch", "fsaverage")
    assert code == 1 and "license-not-accepted" in err
    code, _, err = run(capsys, "--data-dir", str(tmp_path), "--json", "datasets", "validate", "ixi")
    assert code == 1 and json.loads(err)["error"]["code"] == "not-acquired"
    with pytest.raises(SystemExit) as usage:
        main(["datasets", "fetch", "hcp"])
    assert usage.value.code == 2


def test_check_mri(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = write_t1(tmp_path / "t1.nii.gz", shape=(160, 200, 180))
    code, out, _ = run(capsys, "--json", "anatomy", "check-mri", str(good))
    assert code == 0 and json.loads(out)["volume"]["shape"] == [160, 200, 180]
    flat = write_t1(tmp_path / "flat.nii.gz", constant=True)
    assert run(capsys, "anatomy", "check-mri", str(flat))[0] == 1


def test_import_prepare_list_info_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = ["--data-dir", str(tmp_path / "data")]
    recon = write_freesurfer_subject(tmp_path / "recon")
    assert run(capsys, *data, "datasets", "import-freesurfer", str(recon), "--label", "me")[0] == 0
    code, out, _ = run(capsys, *data, "--json", "datasets", "subjects")
    assert code == 0 and json.loads(out)["subjects"][0]["key"] == "local/me"
    assert run(capsys, *data, "datasets", "check-subject", "local/me")[0] == 0
    assert run(capsys, *data, "datasets", "validate", "local")[0] == 0

    code, out, _ = run(capsys, *data, "--json", "anatomy", "prepare", "local/me", "--surfaces", "pial,inflated")
    assert code == 0
    prepared = json.loads(out)
    assert prepared["created"] is True
    asset_id = prepared["assetId"]
    code, out, _ = run(capsys, *data, "anatomy", "prepare", "local/me", "--surfaces", "pial,inflated")
    assert "already prepared" in out

    code, out, _ = run(capsys, *data, "--json", "anatomy", "assets")
    assert json.loads(out)["assets"][0]["surfaces"] == ["pial", "inflated"]
    code, out, _ = run(capsys, *data, "anatomy", "info", asset_id)
    assert code == 0 and "lh.pial" in out and "freesurfer-surface-ras" in out
    assert run(capsys, *data, "anatomy", "verify", asset_id)[0] == 0
    (tmp_path / "data" / "assets" / "anatomy" / asset_id / "rh.inflated.indices.u32").write_bytes(b"")
    code, out, _ = run(capsys, *data, "anatomy", "verify", asset_id)
    assert code == 1 and "FAILED" in out


def test_validate_detects_modified_raw_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = ["--data-dir", str(tmp_path / "data")]
    t1 = write_t1(tmp_path / "t1.nii.gz")
    assert run(capsys, *data, "datasets", "import-mri", str(t1), "--label", "me", "--field-strength", "3")[0] == 0
    stored = tmp_path / "data" / "raw" / "local" / "1" / "mri" / "me" / "T1w.nii.gz"
    stored.write_bytes(stored.read_bytes() + b"\0")
    code, out, _ = run(capsys, *data, "datasets", "validate", "local")
    assert code == 1 and "differs" in out


def test_prepare_without_surfaces_explains_reconstruction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "data"
    write_t1(data / "raw" / "ixi" / get_dataset("ixi").version / "IXI012-HH-1211-T1.nii.gz")
    code, _, err = run(capsys, "--data-dir", str(data), "anatomy", "prepare", "ixi/IXI012-HH-1211")
    assert code == 1 and "no-surfaces" in err and "recon-all" in err
