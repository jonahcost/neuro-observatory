"""fsaverage via mne.datasets.fetch_fsaverage (optional `neuroimaging` extra)."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from neuro_engine import __version__
from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import sha256_file
from neuro_engine.datasets.provenance import (
    AcquiredFile,
    ToolVersion,
    new_record,
    read_record,
    utc_now,
    write_record,
)
from neuro_engine.datasets.storage import DataRoot

# Files the anatomy pipeline reads; their hashes are recorded after MNE has verified the archives.
FSAVERAGE_ANATOMY_FILES = tuple(
    [f"fsaverage/surf/{h}.{s}" for h in ("lh", "rh") for s in ("pial", "white", "inflated", "sphere")]
    + [f"fsaverage/label/{h}.{a}.annot" for h in ("lh", "rh") for a in ("aparc", "aparc.a2009s")]
    + ["fsaverage/mri/T1.mgz", "fsaverage/mri/orig.mgz", "fsaverage/bem/fsaverage-fiducials.fif"]
)

FetchFunction = Callable[[Path], Path]


@contextmanager
def _subjects_dir_env(subjects_dir: Path) -> Iterator[None]:
    """MNE writes SUBJECTS_DIR to ~/.mne/mne-python.json when none is configured;
    setting it in-process prevents that global side effect."""
    previous = os.environ.get("SUBJECTS_DIR")
    os.environ["SUBJECTS_DIR"] = str(subjects_dir)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SUBJECTS_DIR", None)
        else:
            os.environ["SUBJECTS_DIR"] = previous


def _mne_fetch(subjects_dir: Path) -> Path:
    try:
        import mne
    except ImportError:
        raise DatasetError(
            "missing-dependency",
            "fetching fsaverage needs MNE-Python",
            "install the optional extra: cd services/neuro-engine && uv sync --extra neuroimaging",
        ) from None
    return Path(mne.datasets.fetch_fsaverage(subjects_dir=subjects_dir, verbose="error"))


def _mne_version() -> str:
    try:
        import mne

        return str(mne.__version__)
    except ImportError:
        return "unavailable"


def fetch_fsaverage(root: DataRoot, *, accept_license: bool, fetch: FetchFunction = _mne_fetch) -> Path:
    spec = get_dataset("fsaverage")
    if not accept_license:
        raise DatasetError(
            "license-not-accepted",
            f"fsaverage is distributed under the {spec.license.name} ({spec.license.url})",
            "read the license and re-run with --accept-license",
        )
    root.prepare_for_writing()
    subjects_dir = root.raw(spec.id, spec.version)
    subjects_dir.mkdir(parents=True, exist_ok=True)
    with _subjects_dir_env(subjects_dir):
        try:
            fs_dir = fetch(subjects_dir)
        except DatasetError:
            raise
        except Exception as exc:  # MNE/pooch raise many types for network and hash failures
            raise DatasetError(
                "fetch-failed",
                f"MNE could not fetch fsaverage ({type(exc).__name__})",
                "check the network connection and retry; MNE verifies the archive hashes",
            ) from exc
    if fs_dir.resolve() != (subjects_dir / "fsaverage").resolve():
        raise DatasetError("unexpected-layout", "MNE returned fsaverage outside the requested subjects directory")
    missing = [p for p in FSAVERAGE_ANATOMY_FILES if not (subjects_dir / p).is_file()]
    if missing:
        raise DatasetError(
            "incomplete-dataset", f"fsaverage is missing {len(missing)} expected files (first: {missing[0]})", "retry the fetch"
        )
    record = read_record(root, spec.id, spec.version) or new_record(
        spec, tools=[ToolVersion(name="neuro-engine", version=__version__), ToolVersion(name="mne", version=_mne_version())]
    )
    record.license_accepted_at_utc = record.license_accepted_at_utc or utc_now()
    record.upsert_files(
        [
            AcquiredFile(path=p, bytes=(subjects_dir / p).stat().st_size, sha256=sha256_file(subjects_dir / p))
            for p in FSAVERAGE_ANATOMY_FILES
        ]
    )
    write_record(root, record)
    return fs_dir
