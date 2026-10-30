"""Data root layout. One configurable root, outside the repository by default.

    <root>/raw/<dataset>/<version>/                  source files as distributed; never modified after verification
    <root>/raw/<dataset>/<version>.acquisition.json  provenance record
    <root>/downloads/<dataset>/<version>/            partial downloads (*.part); safe to delete
    <root>/derivatives/<dataset>/<version>/          locally computed derivatives (e.g. future recon-all)
    <root>/assets/anatomy/<assetId>/                 app-ready geometry, regenerable
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from neuro_engine.datasets.errors import DatasetError

ENV_DATA_DIR = "NEURO_ENGINE_DATA_DIR"
LOCK_TIMEOUT_S = 30.0


def _safe_component(value: str, label: str) -> str:
    if not value or value in (".", "..") or any(separator in value for separator in ("/", "\\")):
        raise DatasetError("unsafe-path", f"{label} is not a safe path component")
    return value


def ensure_contained(root: Path, path: Path) -> Path:
    """Resolve `path` and require it to remain under `root`."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise DatasetError("unsafe-path", "resolved path escapes the configured data root")
    return resolved


def private_mkdir(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise DatasetError("unsafe-path", f"refusing symlinked directory component {candidate.name}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise DatasetError("unsafe-path", f"{path.name} is not a private directory")
    if os.name == "posix":
        path.chmod(0o700)


@contextmanager
def file_lock(path: Path, *, timeout_s: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """OS-owned interprocess lock; process exit releases it without stale-lock theft."""
    lock = path.with_name(path.name + ".lock")
    private_mkdir(lock.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock, flags, 0o600)
    except OSError as exc:
        raise DatasetError("unsafe-path", f"cannot safely open lock for {path.name}") from exc
    deadline = time.monotonic() + timeout_s
    try:
        if os.name == "posix":
            import fcntl

            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DatasetError(
                            "resource-busy",
                            f"timed out waiting for {path.name}",
                            "retry after the other operation finishes",
                        ) from None
                    time.sleep(0.05)
        else:
            import msvcrt

            while True:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise DatasetError(
                            "resource-busy",
                            f"timed out waiting for {path.name}",
                            "retry after the other operation finishes",
                        ) from None
                    time.sleep(0.05)
        if os.name == "posix":
            try:
                os.fchmod(descriptor, 0o600)
            except OSError:
                pass
        yield
    finally:
        os.close(descriptor)


def default_data_dir(env: Mapping[str, str] | None = None, platform: str | None = None, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "darwin":
        return home / "Library" / "Application Support" / "NeuroObservatory"
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / "NeuroObservatory"
    xdg = env.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".local" / "share") / "neuro-observatory"


def _enclosing_git_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def ensure_outside_version_control(path: Path) -> None:
    """Refuse a data root inside a Git working tree unless Git ignores it."""
    git_root = _enclosing_git_root(path)
    if git_root is None:
        return
    try:
        result = subprocess.run(
            # A child path matches directory-only patterns ("data/") even before the directory exists.
            ["git", "-C", str(git_root), "check-ignore", "-q", "--no-index", str(path / ".probe")],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise DatasetError(
            "data-root-in-repository",
            "the data directory is inside a Git working tree and Git is unavailable to confirm it is ignored",
            f"set {ENV_DATA_DIR} to a directory outside the repository",
        ) from None
    if result.returncode != 0:
        raise DatasetError(
            "data-root-in-repository",
            "the data directory is inside a Git working tree and is not ignored by Git",
            f"set {ENV_DATA_DIR} to a directory outside the repository (MRI and EEG data must never be committed)",
        )


@dataclass(frozen=True, slots=True)
class DataRoot:
    path: Path

    def raw(self, dataset_id: str, version: str) -> Path:
        return self.path / "raw" / _safe_component(dataset_id, "dataset ID") / _safe_component(version, "dataset version")

    def acquisition_record(self, dataset_id: str, version: str) -> Path:
        dataset = _safe_component(dataset_id, "dataset ID")
        safe_version = _safe_component(version, "dataset version")
        return self.path / "raw" / dataset / f"{safe_version}.acquisition.json"

    def downloads(self, dataset_id: str, version: str) -> Path:
        return self.path / "downloads" / _safe_component(dataset_id, "dataset ID") / _safe_component(version, "dataset version")

    def derivatives(self, dataset_id: str, version: str) -> Path:
        return self.path / "derivatives" / _safe_component(dataset_id, "dataset ID") / _safe_component(version, "dataset version")

    def reconstruction_record(self, dataset_id: str, version: str, subject_id: str) -> Path:
        subject = _safe_component(subject_id, "subject ID")
        return self.derivatives(dataset_id, version) / "provenance" / f"{subject}.reconstruction.json"

    @property
    def anatomy_assets(self) -> Path:
        return self.path / "assets" / "anatomy"

    def prepare_for_writing(self) -> None:
        ensure_outside_version_control(self.path)
        private_mkdir(self.path)


def resolve_data_root(configured: Path | str | None = None, env: Mapping[str, str] | None = None) -> DataRoot:
    """Explicit path, else NEURO_ENGINE_DATA_DIR, else the per-user default."""
    env = os.environ if env is None else env
    raw = configured if configured is not None else (env.get(ENV_DATA_DIR) or "").strip() or None
    path = Path(raw).expanduser() if raw is not None else default_data_dir(env)
    if not path.is_absolute():
        path = Path.cwd() / path
    return DataRoot(path.resolve())
