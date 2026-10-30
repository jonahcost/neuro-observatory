from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fake_http import FakeServer

from neuro_engine.datasets.download import (
    DownloadTarget,
    check_url_allowed,
    fetch,
    read_range,
)
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import ExpectedChecksum

URL = "https://example.org/data/file.bin"
ALLOWED = ("example.org/data/",)
BODY = bytes(range(256)) * 40


def target(tmp_path: Path, body: bytes = BODY, *, checksum: bool = True, size: int | None = None) -> DownloadTarget:
    return DownloadTarget(
        url=URL,
        destination=tmp_path / "raw" / "file.bin",
        partial=tmp_path / "downloads" / "file.bin.part",
        size=len(body) if size is None else size,
        checksum=ExpectedChecksum("sha256", hashlib.sha256(body).hexdigest()) if checksum else None,
        label="file.bin",
    )


def test_fresh_download_is_verified_and_moved_into_place(tmp_path: Path) -> None:
    server = FakeServer({URL: BODY})
    progress: list[int] = []
    assert fetch(target(tmp_path), allowed=ALLOWED, opener=server, progress=lambda _l, n, _t: progress.append(n))
    assert (tmp_path / "raw" / "file.bin").read_bytes() == BODY
    assert not (tmp_path / "downloads" / "file.bin.part").exists()
    assert progress[-1] == len(BODY)
    assert server.requests == [(URL, None)]


def test_existing_verified_file_is_not_downloaded_again(tmp_path: Path) -> None:
    server = FakeServer({URL: BODY})
    fetch(target(tmp_path), allowed=ALLOWED, opener=server)
    assert fetch(target(tmp_path), allowed=ALLOWED, opener=server) is False
    assert len(server.requests) == 1


def test_existing_mismatching_file_is_never_overwritten(tmp_path: Path) -> None:
    destination = tmp_path / "raw" / "file.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"x" * len(BODY))
    with pytest.raises(DatasetError) as info:
        fetch(target(tmp_path), allowed=ALLOWED, opener=FakeServer({URL: BODY}))
    assert info.value.code == "existing-file-mismatch"
    assert destination.read_bytes() == b"x" * len(BODY)


def test_interrupted_download_resumes_with_range(tmp_path: Path) -> None:
    server = FakeServer({URL: BODY}, fail_after=3000)
    with pytest.raises(DatasetError) as info:
        fetch(target(tmp_path), allowed=ALLOWED, opener=server)
    assert info.value.code == "network-error"
    partial = tmp_path / "downloads" / "file.bin.part"
    assert partial.stat().st_size == 3000
    assert fetch(target(tmp_path), allowed=ALLOWED, opener=server)
    assert server.requests[-1] == (URL, "bytes=3000-")
    assert (tmp_path / "raw" / "file.bin").read_bytes() == BODY


def test_server_ignoring_range_restarts_from_zero(tmp_path: Path) -> None:
    partial = tmp_path / "downloads" / "file.bin.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"garbage")
    assert fetch(target(tmp_path), allowed=ALLOWED, opener=FakeServer({URL: BODY}, honour_range=False))
    assert (tmp_path / "raw" / "file.bin").read_bytes() == BODY


def test_checksum_mismatch_discards_the_partial(tmp_path: Path) -> None:
    tampered = BODY[:-1] + b"\x00"
    with pytest.raises(DatasetError) as info:
        fetch(target(tmp_path), allowed=ALLOWED, opener=FakeServer({URL: tampered}))
    assert info.value.code == "checksum-mismatch"
    assert not (tmp_path / "downloads" / "file.bin.part").exists()
    assert not (tmp_path / "raw" / "file.bin").exists()


def test_oversized_response_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetError) as info:
        fetch(target(tmp_path, size=100, checksum=False), allowed=ALLOWED, opener=FakeServer({URL: BODY}))
    assert info.value.code == "checksum-mismatch"


def test_http_errors_are_actionable(tmp_path: Path) -> None:
    with pytest.raises(DatasetError) as info:
        fetch(target(tmp_path), allowed=ALLOWED, opener=FakeServer({URL: BODY}, status_override=503))
    assert info.value.code == "http-error" and "503" in info.value.message
    assert info.value.hint


@pytest.mark.parametrize(
    "url",
    ["http://example.org/data/file.bin", "https://evil.example/data/file.bin", "https://example.org/other/file.bin", "file:///etc/passwd"],
)
def test_only_allowed_https_prefixes(url: str) -> None:
    with pytest.raises(DatasetError) as info:
        check_url_allowed(url, ALLOWED)
    assert info.value.code == "disallowed-url"


def test_member_slice_downloads_only_its_bytes(tmp_path: Path) -> None:
    archive = b"H" * 512 + BODY + b"T" * 700
    server = FakeServer({URL: archive}, fail_after=1000)
    member = DownloadTarget(
        url=URL,
        destination=tmp_path / "raw" / "member.bin",
        partial=tmp_path / "downloads" / "member.bin.part",
        size=len(BODY),
        checksum=None,
        label="member",
        member_offset=512,
    )
    with pytest.raises(DatasetError):
        fetch(member, allowed=ALLOWED, opener=server)
    assert fetch(member, allowed=ALLOWED, opener=server)
    assert member.destination.read_bytes() == BODY
    assert server.requests == [(URL, f"bytes=512-{512 + len(BODY) - 1}"), (URL, f"bytes=1512-{512 + len(BODY) - 1}")]


def test_member_slice_never_falls_back_to_the_whole_archive(tmp_path: Path) -> None:
    member = DownloadTarget(
        url=URL,
        destination=tmp_path / "member.bin",
        partial=tmp_path / "member.bin.part",
        size=10,
        checksum=None,
        label="member",
        member_offset=512,
    )
    with pytest.raises(DatasetError) as info:
        fetch(member, allowed=ALLOWED, opener=FakeServer({URL: BODY}, honour_range=False))
    assert info.value.code == "range-unsupported"
    assert not member.partial.exists() or member.partial.stat().st_size == 0


def test_member_slice_requires_size() -> None:
    with pytest.raises(ValueError):
        DownloadTarget(URL, Path("a"), Path("b"), None, None, "x", member_offset=0)


def test_read_range() -> None:
    server = FakeServer({URL: BODY})
    assert read_range(URL, 10, 20, allowed=ALLOWED, opener=server) == BODY[10:30]
    with pytest.raises(DatasetError) as info:
        read_range(URL, 10, 20, allowed=ALLOWED, opener=FakeServer({URL: BODY}, honour_range=False))
    assert info.value.code == "range-unsupported"
    with pytest.raises(DatasetError) as short:
        read_range(URL, len(BODY) - 5, 20, allowed=ALLOWED, opener=server)
    assert short.value.code == "short-read"
