"""Metadata-only inspection of a subject's EEG recording (optional `neuroimaging` extra).

Reports what source localization would need (channel count, sampling rate,
digitised electrode positions, fiducials, coordinate frame). It never reads or
emits sample values and makes no claim that the EEG is anatomically localised.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.subjects import SubjectSource


@dataclass(frozen=True, slots=True)
class EegInspection:
    recording: str
    eeg_channels: int
    other_channels: int
    sampling_rate_hz: float
    duration_s: float
    line_frequency_hz: float | None
    digitized_eeg_positions: int
    fiducials: tuple[str, ...]
    head_shape_points: int
    montage_frame: str | None
    bads: tuple[str, ...]
    annotations: int
    source_localization_ready: bool
    missing_for_source_localization: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return asdict(self)


def _import_mne():  # type: ignore[no-untyped-def]
    try:
        import mne
        import mne_bids
    except ImportError:
        raise DatasetError(
            "missing-dependency",
            "EEG inspection needs MNE-Python and MNE-BIDS",
            "install the optional extra: cd services/neuro-engine && uv sync --extra neuroimaging",
        ) from None
    return mne, mne_bids


def find_eeg_recordings(subject: SubjectSource) -> list[Path]:
    sub_dir = subject.dataset_dir / subject.subject_id
    return sorted(p for p in sub_dir.glob("*/*") if p.suffix in {".fif", ".edf", ".bdf", ".vhdr", ".set"} and "_task-" in p.name)


def inspect_eeg(subject: SubjectSource, recording: Path | None = None) -> EegInspection:
    mne, mne_bids = _import_mne()
    recordings = [recording] if recording is not None else find_eeg_recordings(subject)
    if not recordings:
        raise DatasetError("no-eeg", f"{subject.key} has no EEG recording", "fetch a dataset profile that includes EEG")
    path = recordings[0]
    bids_path = mne_bids.get_bids_path_from_fname(path)
    bids_path.update(root=subject.dataset_dir)
    try:
        raw = mne_bids.read_raw_bids(bids_path, verbose="error")
    except Exception as exc:  # MNE raises many types for malformed recordings
        raise DatasetError("unreadable-eeg", f"{path.name}: MNE-BIDS could not read it ({type(exc).__name__})") from exc
    info = raw.info
    picks = mne.pick_types(info, meg=False, eeg=True, exclude=[])
    dig = info.get("dig") or []
    fiducial_names = {1: "LPA", 2: "NASION", 3: "RPA"}
    fiducials = tuple(
        sorted(fiducial_names.get(int(d["ident"]), "?") for d in dig if int(d["kind"]) == mne.io.constants.FIFF.FIFFV_POINT_CARDINAL)
    )
    eeg_points = sum(1 for d in dig if int(d["kind"]) == mne.io.constants.FIFF.FIFFV_POINT_EEG)
    head_points = sum(1 for d in dig if int(d["kind"]) == mne.io.constants.FIFF.FIFFV_POINT_EXTRA)
    frames = {int(d["coord_frame"]) for d in dig}
    frame = None
    if len(frames) == 1:
        frame = {
            mne.io.constants.FIFF.FIFFV_COORD_HEAD: "head",
            mne.io.constants.FIFF.FIFFV_COORD_DEVICE: "meg-device",
            mne.io.constants.FIFF.FIFFV_COORD_MRI: "mri",
        }.get(frames.pop(), "other")
    missing = []
    if eeg_points < len(picks):
        missing.append(f"digitised positions for all {len(picks)} EEG electrodes (found {eeg_points})")
    if len(fiducials) < 3:
        missing.append("three anatomical fiducials (LPA, nasion, RPA)")
    missing.extend(
        [
            "head-to-MRI coregistration (trans) validated for this subject",
            "BEM or other head conductivity model",
            "forward model, noise covariance and inverse solution",
        ]
    )
    return EegInspection(
        recording=path.name,
        eeg_channels=len(picks),
        other_channels=len(info["ch_names"]) - len(picks),
        sampling_rate_hz=float(info["sfreq"]),
        duration_s=float(raw.times[-1]) if raw.n_times else 0.0,
        line_frequency_hz=float(info["line_freq"]) if info.get("line_freq") else None,
        digitized_eeg_positions=eeg_points,
        fiducials=fiducials,
        head_shape_points=head_points,
        montage_frame=frame,
        bads=tuple(b for b in info["bads"] if b in {info["ch_names"][i] for i in picks}),
        annotations=len(raw.annotations),
        source_localization_ready=False,
        missing_for_source_localization=tuple(missing),
    )
