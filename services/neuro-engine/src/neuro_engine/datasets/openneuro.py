"""OpenNeuro snapshot downloads through the public GraphQL API (no third-party client).

The snapshot listing returns, per file, its size, a versioned S3 URL and an ID
that is either a git-annex key (MD5E-s<size>--<md5>) or a git blob SHA-1; both
are verified after download.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from neuro_engine import __version__
from neuro_engine.datasets.catalog import LARGE_DOWNLOAD_BYTES, get_dataset
from neuro_engine.datasets.download import (
    USER_AGENT,
    DownloadTarget,
    Opener,
    Progress,
    allowed_opener,
    check_url_allowed,
    fetch,
)
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import checksum_from_openneuro_id, sha256_file
from neuro_engine.datasets.provenance import (
    AcquiredFile,
    ToolVersion,
    new_record,
    read_record,
    write_record,
)
from neuro_engine.datasets.storage import DataRoot

GRAPHQL_URL = "https://openneuro.org/crn/graphql"
MAX_GRAPHQL_RESPONSE_BYTES = 10_000_000
MAX_SNAPSHOT_FILES = 10_000
MAX_TREE_DEPTH = 32
MAX_REMOTE_FILE_BYTES = 20_000_000_000
Profile = Literal["anatomy", "full"]

_SUB01_FS = "derivatives/freesurfer/subjects/sub-01"
PROFILES: dict[str, tuple[str, ...]] = {
    # sub-01 BIDS data, plus only the FreeSurfer derivatives the anatomy pipeline reads.
    "anatomy": (
        r"dataset_description\.json",
        r"participants\.(tsv|json)",
        r"README",
        r"CHANGES",
        r"sub-01/.+",
        rf"{_SUB01_FS}/surf/[lr]h\.(pial|white|inflated)",
        rf"{_SUB01_FS}/label/[lr]h\.aparc(\.a2009s|\.DKTatlas)?\.annot",
        rf"{_SUB01_FS}/mri/(T1|orig|rawavg)\.mgz",
        rf"{_SUB01_FS}/bem/[^/]+",
        rf"{_SUB01_FS}/scripts/build-stamp\.txt",
    ),
    "full": (r".+",),
}

PostJson = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RemoteFile:
    path: str
    size: int
    file_id: str
    url: str


@dataclass(frozen=True, slots=True)
class FetchReport:
    dataset_id: str
    version: str
    downloaded: int
    already_present: int
    total_bytes: int


def default_post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    check_url_allowed(url, ("openneuro.org/crn/graphql",))
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        response = allowed_opener(("openneuro.org/crn/graphql",))(request, 60)
        try:
            payload = response.read(MAX_GRAPHQL_RESPONSE_BYTES + 1)
        finally:
            response.close()
        if len(payload) > MAX_GRAPHQL_RESPONSE_BYTES:
            raise DatasetError("openneuro-api", "OpenNeuro API response exceeds the safety limit", "retry later")
        return json.loads(payload)
    except urllib.error.HTTPError as exc:
        raise DatasetError("http-error", f"OpenNeuro API returned HTTP {exc.code}", "retry later") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise DatasetError(
            "network-error", f"OpenNeuro API request failed ({type(exc).__name__})", "check the network connection"
        ) from None


def _safe_relative(path: str) -> str:
    parts = path.split("/")
    if (
        PurePosixPath(path).is_absolute()
        or any(part in ("", ".", "..") for part in parts)
        or not re.fullmatch(r"[A-Za-z0-9._/+-]{1,256}", path)
    ):
        raise DatasetError("unsafe-path", f"OpenNeuro listed an unsafe path '{path[:80]}'", "report this upstream")
    return path


def list_snapshot(dataset_id: str, tag: str, *, post_json: PostJson = default_post_json) -> list[RemoteFile]:
    """Every file in the snapshot (recursing into directories), excluding DataLad metadata."""
    files: list[RemoteFile] = []
    visited_trees: set[str] = set()

    def query(tree: str | None) -> list[dict[str, Any]]:
        args = f'(tree: "{tree}")' if tree else ""
        body = {
            "query": f'{{ snapshot(datasetId: "{dataset_id}", tag: "{tag}") {{ files{args} {{ filename size directory id urls }} }} }}'
        }
        data = post_json(GRAPHQL_URL, body)
        if "errors" in data or not isinstance(data.get("data"), dict) or not data["data"].get("snapshot"):
            raise DatasetError(
                "openneuro-api",
                f"OpenNeuro did not return snapshot {dataset_id} {tag}",
                "the API may have changed; download manually from the DOI and use local import",
            )
        return data["data"]["snapshot"]["files"]

    def walk(prefix: str, tree: str | None, depth: int = 0) -> None:
        if depth > MAX_TREE_DEPTH:
            raise DatasetError("openneuro-api", "OpenNeuro snapshot tree exceeds the depth limit", "use local import")
        if tree is not None:
            if tree in visited_trees:
                raise DatasetError("openneuro-api", "OpenNeuro snapshot tree contains a cycle", "report this upstream")
            visited_trees.add(tree)
        for entry in query(tree):
            name = str(entry["filename"])
            path = _safe_relative(f"{prefix}{name}")
            if entry.get("directory"):
                if name != ".datalad":
                    walk(f"{path}/", str(entry["id"]), depth + 1)
                continue
            if len(files) >= MAX_SNAPSHOT_FILES:
                raise DatasetError("openneuro-api", "OpenNeuro snapshot exceeds the file-count safety limit", "use a smaller profile")
            size = int(entry["size"])
            if not 0 <= size <= MAX_REMOTE_FILE_BYTES:
                raise DatasetError("openneuro-api", f"OpenNeuro listed an invalid size for {path}", "report this upstream")
            urls = entry.get("urls") or []
            if not urls:
                raise DatasetError("openneuro-api", f"no download URL for {path}", "retry later")
            files.append(RemoteFile(path=path, size=size, file_id=str(entry["id"]), url=str(urls[0])))

    walk("", None)
    return files


def select_profile(files: list[RemoteFile], profile: str) -> list[RemoteFile]:
    patterns = PROFILES.get(profile)
    if patterns is None:
        raise DatasetError("unknown-profile", f"unknown profile '{profile}'", f"choose one of: {', '.join(PROFILES)}")
    compiled = [re.compile(p) for p in patterns]
    return [f for f in files if any(c.fullmatch(f.path) for c in compiled)]


def fetch_openneuro(
    root: DataRoot,
    dataset_id: str = "ds000248",
    *,
    profile: str = "anatomy",
    confirm_large: bool = False,
    post_json: PostJson = default_post_json,
    opener: Opener | None = None,
    progress: Progress | None = None,
) -> FetchReport:
    spec = get_dataset(dataset_id)
    if spec.method != "openneuro-graphql":
        raise DatasetError("wrong-method", f"{dataset_id} is not an OpenNeuro dataset")
    selected = select_profile(list_snapshot(spec.id, spec.version, post_json=post_json), profile)
    if not selected:
        raise DatasetError("empty-selection", f"profile '{profile}' matched no files in {spec.id} {spec.version}")
    total = sum(f.size for f in selected)
    if total > LARGE_DOWNLOAD_BYTES and not confirm_large:
        raise DatasetError(
            "large-download",
            f"profile '{profile}' is {total / 1e9:.2f} GB ({len(selected)} files)",
            "re-run with --confirm-large to proceed",
        )
    root.prepare_for_writing()
    raw = root.raw(spec.id, spec.version)
    downloads = root.downloads(spec.id, spec.version)
    allowed = (f"s3.amazonaws.com/openneuro.org/{spec.id}/", f"openneuro.org/crn/datasets/{spec.id}/")
    record = read_record(root, spec.id, spec.version) or new_record(
        spec, profile=profile, tools=[ToolVersion(name="neuro-engine", version=__version__)]
    )
    if record.profile != profile and profile == "full":
        record.profile = "full"
    known = record.file_index()
    acquired: list[AcquiredFile] = []
    downloaded = present = 0
    try:
        for remote in selected:
            checksum = checksum_from_openneuro_id(remote.file_id, remote.size)
            if checksum is None:
                raise DatasetError(
                    "unsupported-checksum",
                    f"OpenNeuro listed an unsupported checksum ID for {remote.path}",
                    "the snapshot format may have changed; use the DOI for a manual verified acquisition",
                )
            destination = raw / remote.path
            changed = fetch(
                DownloadTarget(
                    url=remote.url,
                    destination=destination,
                    partial=downloads / f"{remote.path}.part",
                    size=remote.size,
                    checksum=checksum,
                    label=f"{spec.id}/{remote.path}",
                ),
                allowed=allowed,
                opener=opener,
                progress=progress,
            )
            downloaded += int(changed)
            present += int(not changed)
            previous = known.get(remote.path)
            digest = previous.sha256 if previous is not None and not changed else sha256_file(destination)
            acquired.append(
                AcquiredFile(
                    path=remote.path,
                    bytes=remote.size,
                    sha256=digest,
                    upstream_checksum=checksum.label() if checksum else None,
                    source_url=remote.url,
                )
            )
    finally:
        if acquired:
            record.upsert_files(acquired)
            write_record(root, record)
    return FetchReport(spec.id, spec.version, downloaded, present, total)
