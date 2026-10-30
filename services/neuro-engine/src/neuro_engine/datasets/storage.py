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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from neuro_engine.datasets.errors import DatasetError

ENV_DATA_DIR = "NEURO_ENGINE_DATA_DIR"


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
        return self.path / "raw" / dataset_id / version

    def acquisition_record(self, dataset_id: str, version: str) -> Path:
        return self.path / "raw" / dataset_id / f"{version}.acquisition.json"

    def downloads(self, dataset_id: str, version: str) -> Path:
        return self.path / "downloads" / dataset_id / version

    def derivatives(self, dataset_id: str, version: str) -> Path:
        return self.path / "derivatives" / dataset_id / version

    @property
    def anatomy_assets(self) -> Path:
        return self.path / "assets" / "anatomy"

    def prepare_for_writing(self) -> None:
        ensure_outside_version_control(self.path)
        self.path.mkdir(parents=True, exist_ok=True)


def resolve_data_root(configured: Path | str | None = None, env: Mapping[str, str] | None = None) -> DataRoot:
    """Explicit path, else NEURO_ENGINE_DATA_DIR, else the per-user default."""
    env = os.environ if env is None else env
    raw = configured if configured is not None else (env.get(ENV_DATA_DIR) or "").strip() or None
    path = Path(raw).expanduser() if raw is not None else default_data_dir(env)
    if not path.is_absolute():
        path = Path.cwd() / path
    return DataRoot(path.resolve())
