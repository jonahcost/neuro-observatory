from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from fake_http import FakeServer

from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.openneuro import (
    GRAPHQL_URL,
    fetch_openneuro,
    list_snapshot,
    select_profile,
)
from neuro_engine.datasets.provenance import read_record
from neuro_engine.datasets.storage import DataRoot

S3 = "https://s3.amazonaws.com/openneuro.org/ds000248"


def git_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def annex_key(data: bytes, ext: str) -> str:
    return f"MD5E-s{len(data)}--{hashlib.md5(data).hexdigest()}{ext}"


CONTENT = {
    "dataset_description.json": b'{"Name": "synthetic", "BIDSVersion": "1.9.0"}',
    "participants.tsv": b"participant_id\nsub-01\n",
    "README": b"synthetic test dataset\n",
    "sub-01/anat/sub-01_T1w.nii.gz": b"\x1f\x8b synthetic bytes",
    "sub-emptyroom/meg/sub-emptyroom_meg.fif": b"not selected",
    "derivatives/freesurfer/subjects/sub-01/surf/lh.pial": b"surface",
    "derivatives/freesurfer/subjects/sub-01/surf/lh.sphere": b"not selected",
    ".bidsignore": b"*_scans.tsv\n",
}
ANNEXED = {"sub-01/anat/sub-01_T1w.nii.gz", "derivatives/freesurfer/subjects/sub-01/surf/lh.pial"}


def file_id(path: str) -> str:
    data = CONTENT[path]
    return annex_key(data, ".nii.gz" if path.endswith(".nii.gz") else "") if path in ANNEXED else git_sha1(data)


class FakeGraphQL:
    """Serves the snapshot tree one directory level per query, like OpenNeuro."""

    def __init__(self, extra: list[dict[str, Any]] | None = None) -> None:
        self.trees: dict[str | None, list[dict[str, Any]]] = {}
        self.queries: list[str] = []
        for path, data in CONTENT.items():
            parts = path.split("/")
            parent: str | None = None
            for depth, name in enumerate(parts):
                listing = self.trees.setdefault(parent, [])
                if depth == len(parts) - 1:
                    listing.append(
                        {"filename": name, "size": len(data), "directory": False, "id": file_id(path),
                         "urls": [f"{S3}/{path}?versionId=v1"]}
                    )  # fmt: skip
                else:
                    tree_id = "tree-" + "/".join(parts[: depth + 1])
                    if not any(e["id"] == tree_id for e in listing):
                        listing.append({"filename": name, "size": 0, "directory": True, "id": tree_id, "urls": []})
                    parent = tree_id
        self.trees[None].append({"filename": ".datalad", "size": 0, "directory": True, "id": "tree-datalad", "urls": []})
        self.trees[None].extend(extra or [])

    def __call__(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        assert url == GRAPHQL_URL
        query = body["query"]
        self.queries.append(query)
        assert 'snapshot(datasetId: "ds000248", tag: "1.2.4")' in query
        match = re.search(r'tree: "([^"]+)"', query)
        tree = match[1] if match else None
        assert tree != "tree-datalad"
        return {"data": {"snapshot": {"files": self.trees[tree]}}}


def server() -> FakeServer:
    return FakeServer({f"{S3}/{path}?versionId=v1": data for path, data in CONTENT.items()})


def test_listing_recurses_and_skips_datalad() -> None:
    files = list_snapshot("ds000248", "1.2.4", post_json=FakeGraphQL())
    assert sorted(f.path for f in files) == sorted(CONTENT)


def test_unsafe_paths_from_the_server_are_rejected() -> None:
    evil = {"filename": "../escape", "size": 1, "directory": False, "id": "x", "urls": [f"{S3}/x"]}
    with pytest.raises(DatasetError) as info:
        list_snapshot("ds000248", "1.2.4", post_json=FakeGraphQL([evil]))
    assert info.value.code == "unsafe-path"


def test_api_errors_are_actionable() -> None:
    with pytest.raises(DatasetError) as info:
        list_snapshot("ds000248", "1.2.4", post_json=lambda _u, _b: {"errors": [{"message": "nope"}]})
    assert info.value.code == "openneuro-api" and info.value.hint


def test_anatomy_profile_selects_subject_and_needed_derivatives() -> None:
    selected = {f.path for f in select_profile(list_snapshot("ds000248", "1.2.4", post_json=FakeGraphQL()), "anatomy")}
    assert selected == {
        "dataset_description.json",
        "participants.tsv",
        "README",
        "sub-01/anat/sub-01_T1w.nii.gz",
        "derivatives/freesurfer/subjects/sub-01/surf/lh.pial",
    }
    with pytest.raises(DatasetError):
        select_profile([], "everything")


def test_fetch_verifies_checksums_and_records_provenance(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "data")
    fake = server()
    report = fetch_openneuro(root, post_json=FakeGraphQL(), opener=fake)
    assert (report.downloaded, report.already_present) == (5, 0)
    base = root.raw("ds000248", "1.2.4")
    assert (base / "sub-01/anat/sub-01_T1w.nii.gz").read_bytes() == CONTENT["sub-01/anat/sub-01_T1w.nii.gz"]
    assert not (base / "sub-emptyroom").exists()
    record = read_record(root, "ds000248", "1.2.4")
    assert record is not None and record.profile == "anatomy" and record.license_id == "CC0-1.0"
    entry = record.file_index()["sub-01/anat/sub-01_T1w.nii.gz"]
    assert entry.upstream_checksum is not None and entry.upstream_checksum.startswith("md5:")
    assert record.file_index()["README"].upstream_checksum.startswith("git-sha1:")  # type: ignore[union-attr]

    again = fetch_openneuro(root, post_json=FakeGraphQL(), opener=fake)
    assert (again.downloaded, again.already_present) == (0, 5)
    assert len(fake.requests) == 5


def test_corrupted_upstream_file_is_rejected(tmp_path: Path) -> None:
    fake = server()
    fake.files[f"{S3}/README?versionId=v1"] = b"X" * len(CONTENT["README"])
    with pytest.raises(DatasetError) as info:
        fetch_openneuro(DataRoot(tmp_path), post_json=FakeGraphQL(), opener=fake)
    assert info.value.code == "checksum-mismatch"


def test_large_profile_needs_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("neuro_engine.datasets.openneuro.LARGE_DOWNLOAD_BYTES", 10)
    with pytest.raises(DatasetError) as info:
        fetch_openneuro(DataRoot(tmp_path), profile="full", post_json=FakeGraphQL(), opener=server())
    assert info.value.code == "large-download" and "--confirm-large" in (info.value.hint or "")
    report = fetch_openneuro(DataRoot(tmp_path), profile="full", confirm_large=True, post_json=FakeGraphQL(), opener=server())
    assert report.downloaded == len(CONTENT)


def test_downloads_are_restricted_to_the_dataset_bucket(tmp_path: Path) -> None:
    graph = FakeGraphQL()
    graph.trees[None][2]["urls"] = ["https://elsewhere.example/README"]
    with pytest.raises(DatasetError) as info:
        fetch_openneuro(DataRoot(tmp_path), post_json=graph, opener=server())
    assert info.value.code == "disallowed-url"
