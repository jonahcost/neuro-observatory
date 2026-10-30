"""In-memory HTTP opener for download tests (no network)."""

from __future__ import annotations

import io
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str], fail_after: int | None = None, url: str = "") -> None:
        self.status = status
        self.headers = headers
        self._body = io.BytesIO(body)
        self._fail_after = fail_after
        self._sent = 0
        self.closed = False
        self.url = url

    def read(self, size: int = -1, /) -> bytes:
        if self._fail_after is not None and self._sent >= self._fail_after:
            raise TimeoutError("simulated interruption")
        if self._fail_after is not None:
            size = min(size if size >= 0 else self._fail_after, self._fail_after - self._sent)
        chunk = self._body.read(size)
        self._sent += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def geturl(self) -> str:
        return self.url


@dataclass
class FakeServer:
    files: dict[str, bytes]
    honour_range: bool = True
    fail_after: int | None = None
    status_override: int | None = None
    requests: list[tuple[str, str | None]] = field(default_factory=list)

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        url = request.full_url
        range_header = request.get_header("Range")
        self.requests.append((url, range_header))
        if self.status_override is not None:
            raise urllib.error.HTTPError(url, self.status_override, "error", {}, None)  # type: ignore[arg-type]
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)  # type: ignore[arg-type]
        body = self.files[url]
        fail_after, self.fail_after = self.fail_after, None
        if range_header and self.honour_range:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
            assert match is not None
            start = int(match[1])
            end = int(match[2]) if match[2] else len(body) - 1
            return FakeResponse(
                206, body[start : end + 1], {"Content-Range": f"bytes {start}-{end}/{len(body)}"}, fail_after, url
            )
        return FakeResponse(200, body, {}, fail_after, url)
