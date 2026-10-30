"""File checksums. Upstream checksums are verified when published; SHA-256 is always recorded."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from neuro_engine.datasets.errors import DatasetError

CHUNK_BYTES = 1 << 20
_ANNEX_KEY = re.compile(r"^(?P<backend>MD5E?|SHA256E?)-s(?P<size>\d+)--(?P<digest>[0-9a-f]+)(?:\.[^/]*)?$")
_GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")


def _digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    return _digest(path, "sha256")


def md5_file(path: Path) -> str:
    return _digest(path, "md5")


def git_blob_sha1(path: Path) -> str:
    """Git object ID of a file's contents (what OpenNeuro reports for non-annexed files)."""
    h = hashlib.sha1()
    h.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class ExpectedChecksum:
    algorithm: Literal["md5", "sha256", "git-sha1"]
    digest: str

    def label(self) -> str:
        return f"{self.algorithm}:{self.digest}"

    def matches(self, path: Path) -> bool:
        if self.algorithm == "md5":
            return md5_file(path) == self.digest
        if self.algorithm == "sha256":
            return sha256_file(path) == self.digest
        return git_blob_sha1(path) == self.digest


def checksum_from_openneuro_id(file_id: str, size: int) -> ExpectedChecksum | None:
    """OpenNeuro file IDs are git-annex keys (MD5E-s<size>--<md5>.<ext>) or git blob SHA-1s."""
    match = _ANNEX_KEY.match(file_id)
    if match:
        if int(match["size"]) != size:
            raise DatasetError(
                "inconsistent-listing", f"file key records {match['size']} bytes but the listing says {size}", "retry later"
            )
        algorithm = "md5" if match["backend"].startswith("MD5") else "sha256"
        return ExpectedChecksum(algorithm, match["digest"])  # type: ignore[arg-type]
    if _GIT_SHA1.match(file_id):
        return ExpectedChecksum("git-sha1", file_id)
    return None
