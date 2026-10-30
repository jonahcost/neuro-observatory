"""Resumable, verified HTTPS downloads with the standard library.

A file reaches its final path only after its size and checksum match; until
then it lives as `<downloads>/<relpath>.part` and later runs resume it with an
HTTP Range request.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from neuro_engine import __version__
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import CHUNK_BYTES, ExpectedChecksum
from neuro_engine.datasets.storage import file_lock, private_mkdir

USER_AGENT = f"neuro-observatory-engine/{__version__} (local research tool)"
TIMEOUT_S = 60.0

Progress = Callable[[str, int, int | None], None]


class Response(Protocol):
    status: int
    headers: object

    def read(self, size: int = -1, /) -> bytes: ...

    def close(self) -> None: ...

    def geturl(self) -> str: ...


Opener = Callable[[urllib.request.Request, float], Response]


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: tuple[str, ...]) -> None:
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urljoin(req.full_url, newurl)
        check_url_allowed(target, self.allowed)
        return super().redirect_request(req, fp, code, msg, headers, target)


def allowed_opener(allowed: tuple[str, ...]) -> Opener:
    opener = urllib.request.build_opener(_AllowedRedirectHandler(allowed))
    return lambda request, timeout: opener.open(request, timeout=timeout)


@dataclass(frozen=True, slots=True)
class DownloadTarget:
    """`member_offset` selects the byte slice [member_offset, member_offset + size) of a larger remote file."""

    url: str
    destination: Path
    partial: Path
    size: int | None
    checksum: ExpectedChecksum | None
    label: str
    member_offset: int | None = None

    def __post_init__(self) -> None:
        if self.member_offset is not None and self.size is None:
            raise ValueError("a byte-range target needs a size")


def check_url_allowed(url: str, allowed: tuple[str, ...]) -> None:
    """Only HTTPS URLs whose `host + path` starts with an allowed prefix."""
    parts = urlsplit(url)
    location = f"{parts.hostname or ''}{parts.path}"
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or not any(location == prefix or (prefix.endswith("/") and location.startswith(prefix)) for prefix in allowed)
    ):
        raise DatasetError(
            "disallowed-url",
            f"refusing to download from {parts.scheme}://{parts.hostname}{parts.path}",
            "only the documented dataset hosts are allowed (ADR-0010)",
        )


def read_range(url: str, start: int, length: int, *, allowed: tuple[str, ...], opener: Opener | None = None) -> bytes:
    """Read a small byte range (e.g. a tar header). The server must honour Range."""
    check_url_allowed(url, allowed)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": f"bytes={start}-{start + length - 1}"})
    response = _open(opener or allowed_opener(allowed), request, url)
    try:
        _check_final_url(response, allowed)
        if response.status != 206 or _content_range_start(response) != start:
            raise DatasetError(
                "range-unsupported",
                "the server did not honour the byte-range request",
                "use local import instead of a ranged fetch",
            )
        data = response.read(length + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DatasetError("network-error", f"range read failed ({type(exc).__name__})", "retry later") from None
    finally:
        response.close()
    if len(data) != length:
        raise DatasetError("short-read", f"expected {length} bytes, received {len(data)}", "retry later")
    return data


def fetch(
    target: DownloadTarget,
    *,
    allowed: tuple[str, ...],
    opener: Opener | None = None,
    progress: Progress | None = None,
    validate: Callable[[Path], None] | None = None,
) -> bool:
    """Download and verify one file. Returns False when it was already present and verified."""
    check_url_allowed(target.url, allowed)
    private_mkdir(target.partial.parent)
    with file_lock(target.partial):
        return _fetch_locked(target, allowed=allowed, opener=opener, progress=progress, validate=validate)


def _fetch_locked(
    target: DownloadTarget,
    *,
    allowed: tuple[str, ...],
    opener: Opener | None,
    progress: Progress | None,
    validate: Callable[[Path], None] | None,
) -> bool:
    if target.destination.is_symlink():
        raise DatasetError("unsafe-path", f"{target.label}: destination path is a symlink")
    if target.destination.is_file():
        if _verified(target, target.destination):
            if validate is not None:
                validate(target.destination)
            if os.name == "posix":
                target.destination.chmod(0o600)
            return False
        raise DatasetError(
            "existing-file-mismatch",
            f"{target.label} already exists but does not match the expected size or checksum",
            "raw files are never overwritten; move it aside and fetch again",
        )
    if target.partial.is_symlink():
        raise DatasetError("unsafe-path", f"{target.label}: partial download path is a symlink")
    offset = target.partial.stat().st_size if target.partial.is_file() else 0
    if target.size is not None and offset > target.size:
        target.partial.unlink()
        offset = 0
    if target.size is None or offset < target.size:
        _transfer(target, offset, opener or allowed_opener(allowed), allowed, progress)
    if not _verified(target, target.partial):
        target.partial.unlink(missing_ok=True)
        raise DatasetError(
            "checksum-mismatch",
            f"{target.label} failed size/checksum verification and was discarded",
            "re-run the fetch; if it fails again the upstream file may have changed",
        )
    if validate is not None:
        try:
            validate(target.partial)
        except DatasetError:
            target.partial.unlink(missing_ok=True)
            raise
    private_mkdir(target.destination.parent)
    try:
        os.link(target.partial, target.destination)
    except FileExistsError:
        if target.destination.is_symlink():
            raise DatasetError("unsafe-path", f"{target.label}: destination path became a symlink") from None
        if _verified(target, target.destination):
            target.partial.unlink(missing_ok=True)
            return False
        raise DatasetError(
            "existing-file-mismatch",
            f"{target.label} was created concurrently with different contents",
            "move the conflicting file aside and retry",
        ) from None
    target.partial.unlink()
    if os.name == "posix":
        target.destination.chmod(0o600)
    return True


def _open(opener: Opener, request: urllib.request.Request, label: str) -> Response:
    try:
        return opener(request, TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        raise DatasetError(
            "http-error", f"{label}: server returned HTTP {exc.code}", "check connectivity or retry later"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DatasetError(
            "network-error",
            f"{label}: download failed ({type(exc).__name__})",
            "check the network connection; partial files are kept and the next run resumes them",
        ) from None


def _content_range_start(response: Response) -> int | None:
    get = getattr(response.headers, "get", None)
    header = get("Content-Range") if callable(get) else None
    if not header or not str(header).startswith("bytes "):
        return None
    try:
        return int(str(header)[6:].split("-", 1)[0])
    except ValueError:
        return None


def _check_final_url(response: Response, allowed: tuple[str, ...]) -> None:
    geturl = getattr(response, "geturl", None)
    if callable(geturl):
        check_url_allowed(str(geturl()), allowed)


def _transfer(
    target: DownloadTarget,
    offset: int,
    opener: Opener,
    allowed: tuple[str, ...],
    progress: Progress | None,
) -> None:
    headers = {"User-Agent": USER_AGENT}
    base = target.member_offset
    if base is not None:
        assert target.size is not None
        headers["Range"] = f"bytes={base + offset}-{base + target.size - 1}"
    elif offset:
        headers["Range"] = f"bytes={offset}-"
    response = _open(opener, urllib.request.Request(target.url, headers=headers), target.label)
    try:
        _check_final_url(response, allowed)
        mode = "ab"
        if "Range" in headers:
            expected_start = (base or 0) + offset
            if response.status != 206 or _content_range_start(response) != expected_start:
                if base is not None:
                    # Never fall back to streaming the whole archive.
                    raise DatasetError(
                        "range-unsupported",
                        f"{target.label}: the server did not honour the byte-range request",
                        "use local import instead of a ranged fetch",
                    )
                mode, offset = "wb", 0
        received = offset
        flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "ab" else os.O_TRUNC)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target.partial, flags, 0o600)
        with os.fdopen(descriptor, mode) as out:
            while chunk := response.read(CHUNK_BYTES):
                out.write(chunk)
                received += len(chunk)
                if target.size is not None and received > target.size:
                    break
                if progress is not None:
                    progress(target.label, received, target.size)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DatasetError(
            "network-error",
            f"{target.label}: connection interrupted ({type(exc).__name__})",
            "re-run the same command to resume",
        ) from None
    finally:
        response.close()


def _verified(target: DownloadTarget, path: Path) -> bool:
    if target.size is not None and path.stat().st_size != target.size:
        return False
    return target.checksum is None or target.checksum.matches(path)
