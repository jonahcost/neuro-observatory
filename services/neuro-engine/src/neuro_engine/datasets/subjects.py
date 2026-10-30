"""Dataset-independent view of the subjects present under a data root.

Subject keys: `fsaverage`, `ds000248/sub-01`, `ixi/IXI012-HH-1211`, `local/<label>`.
A subject has a T1 volume, a FreeSurfer subject directory, or both; surfaces
are only ever read from a FreeSurfer reconstruction, never synthesised.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.anatomy.surfaces import HEMISPHERES, SURFACE_KINDS
from neuro_engine.anatomy.volumes import (
    Finding,
    check_mri,
    load_volume_info,
    same_voxel_grid,
)
from neuro_engine.datasets.catalog import (
    DatasetSpec,
    MriAcquisitionFacts,
    get_dataset,
)
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.ixi import SITE_FACTS, parse_ixi_t1_name
from neuro_engine.datasets.provenance import read_record
from neuro_engine.datasets.storage import DataRoot

_BIDS_SUBJECT = re.compile(r"^sub-[A-Za-z0-9]+$")
_LOCAL_T1 = re.compile(r"^T1w\.(nii|nii\.gz|mgz|mgh)$")


@dataclass(frozen=True, slots=True)
class SubjectSource:
    key: str
    spec: DatasetSpec
    subject_id: str
    session_id: str | None
    display_name: str
    dataset_dir: Path
    t1: Path | None
    freesurfer_dir: Path | None
    acquisition: MriAcquisitionFacts

    @property
    def has_surfaces(self) -> bool:
        return self.freesurfer_dir is not None and all(
            (self.freesurfer_dir / "surf" / f"{h}.{k}").is_file() for h in HEMISPHERES for k in SURFACE_KINDS
        )

    @property
    def data_root(self) -> Path:
        return self.dataset_dir.parents[2]

    def relative(self, path: Path) -> str:
        """Data-root-relative POSIX path, as recorded in provenance (never absolute)."""
        return path.relative_to(self.data_root).as_posix()

    def summary(self) -> dict[str, object]:
        return {
            "key": self.key,
            "dataset": f"{self.spec.id} {self.spec.version}",
            "anatomyKind": self.spec.anatomy_kind,
            "displayName": self.display_name,
            "t1": self.relative(self.t1) if self.t1 else None,
            "freesurfer": self.relative(self.freesurfer_dir) if self.freesurfer_dir else None,
            "surfacesAvailable": self.has_surfaces,
            "fieldStrengthTesla": self.acquisition.field_strength_tesla,
            "acquisitionSource": self.acquisition.source,
        }


def _existing(path: Path) -> Path | None:
    return path if path.exists() else None


def _fsaverage(root: DataRoot) -> list[SubjectSource]:
    spec = get_dataset("fsaverage")
    base = root.raw(spec.id, spec.version)
    fs = base / "fsaverage"
    if not fs.is_dir():
        return []
    return [
        SubjectSource(
            key="fsaverage",
            spec=spec,
            subject_id="fsaverage",
            session_id=None,
            display_name="fsaverage template (MNI305)",
            dataset_dir=base,
            t1=_existing(fs / "mri" / "T1.mgz"),
            freesurfer_dir=fs,
            acquisition=spec.acquisition,
        )
    ]


def _ds000248(root: DataRoot) -> list[SubjectSource]:
    spec = get_dataset("ds000248")
    base = root.raw(spec.id, spec.version)
    if not base.is_dir():
        return []
    subjects = []
    for sub_dir in sorted(p for p in base.iterdir() if p.is_dir() and _BIDS_SUBJECT.match(p.name)):
        if sub_dir.name == "sub-emptyroom":
            continue
        fs = base / "derivatives" / "freesurfer" / "subjects" / sub_dir.name
        subjects.append(
            SubjectSource(
                key=f"{spec.id}/{sub_dir.name}",
                spec=spec,
                subject_id=sub_dir.name,
                session_id=None,
                display_name=f"{spec.id} {sub_dir.name} (1.5 T MPRAGE)",
                dataset_dir=base,
                t1=_existing(sub_dir / "anat" / f"{sub_dir.name}_T1w.nii.gz"),
                freesurfer_dir=fs if fs.is_dir() else None,
                acquisition=spec.acquisition,
            )
        )
    return subjects


def _ixi(root: DataRoot) -> list[SubjectSource]:
    spec = get_dataset("ixi")
    base = root.raw(spec.id, spec.version)
    if not base.is_dir():
        return []
    derivatives = root.derivatives(spec.id, spec.version) / "freesurfer"
    subjects = []
    for t1 in sorted(base.glob("IXI*-T1.nii.gz")):
        try:
            ixi = parse_ixi_t1_name(t1.name)
        except DatasetError:
            continue
        fs = derivatives / ixi.subject_id
        subjects.append(
            SubjectSource(
                key=f"ixi/{ixi.subject_id}",
                spec=spec,
                subject_id=ixi.subject_id,
                session_id=None,
                display_name=f"IXI {ixi.subject_id} ({SITE_FACTS[ixi.site].field_strength_tesla:g} T)",
                dataset_dir=base,
                t1=t1,
                freesurfer_dir=fs if fs.is_dir() else None,
                acquisition=SITE_FACTS[ixi.site],
            )
        )
    return subjects


def _local(root: DataRoot) -> list[SubjectSource]:
    spec = get_dataset("local")
    base = root.raw(spec.id, spec.version)
    if not base.is_dir():
        return []
    record = read_record(root, spec.id, spec.version)
    declared = record.declared_acquisition if record else {}
    labels = {p.name for sub in ("mri", "freesurfer") if (base / sub).is_dir() for p in (base / sub).iterdir() if p.is_dir()}
    subjects = []
    for label in sorted(labels):
        t1s = sorted(p for p in (base / "mri" / label).glob("T1w.*") if _LOCAL_T1.match(p.name)) if (base / "mri" / label).is_dir() else []
        fs = base / "freesurfer" / label
        facts = declared.get(label)
        acquisition = MriAcquisitionFacts(
            facts.field_strength_tesla if facts else None,
            facts.sequence if facts else None,
            facts.scanner if facts else None,
            "user-declared",
        )
        subjects.append(
            SubjectSource(
                key=f"local/{label}",
                spec=spec,
                subject_id=label,
                session_id=None,
                display_name=f"Local subject '{label}'",
                dataset_dir=base,
                t1=t1s[0] if t1s else None,
                freesurfer_dir=fs if fs.is_dir() else None,
                acquisition=acquisition,
            )
        )
    return subjects


def list_subjects(root: DataRoot) -> list[SubjectSource]:
    return [*_fsaverage(root), *_ds000248(root), *_ixi(root), *_local(root)]


def resolve_subject(root: DataRoot, key: str) -> SubjectSource:
    for subject in list_subjects(root):
        if subject.key == key:
            return subject
    raise DatasetError(
        "unknown-subject",
        f"no subject '{key}' under the data root",
        "run 'neuro-engine datasets subjects' to list available subjects, or fetch/import one first",
    )


def check_subject(subject: SubjectSource) -> list[Finding]:
    """Consistency checks that need no network and no FreeSurfer installation."""
    findings: list[Finding] = []
    if subject.t1 is None and subject.freesurfer_dir is None:
        return [Finding("error", "no-anatomy", "neither a T1 volume nor a FreeSurfer subject is present")]
    t1_info = None
    if subject.t1 is not None:
        try:
            check = check_mri(subject.t1, read_data=True)
            t1_info = check.info
            findings.extend(check.findings)
        except AnatomyError as exc:
            findings.append(Finding("error", exc.code, exc.message))
    if subject.freesurfer_dir is None:
        findings.append(
            Finding(
                "info",
                "no-reconstruction",
                "no FreeSurfer reconstruction; cortical surfaces need recon-all or FastSurfer (see pipelines/mri-reconstruction)",
            )
        )
    else:
        missing = [
            f"surf/{h}.{k}" for h in HEMISPHERES for k in SURFACE_KINDS if not (subject.freesurfer_dir / "surf" / f"{h}.{k}").is_file()
        ]
        if missing:
            findings.append(Finding("error", "missing-surfaces", f"missing {', '.join(missing)}"))
        rawavg = subject.freesurfer_dir / "mri" / "rawavg.mgz"
        if t1_info is not None and rawavg.is_file():
            try:
                same = same_voxel_grid(t1_info, load_volume_info(rawavg))
            except AnatomyError as exc:
                findings.append(Finding("error", exc.code, exc.message))
            else:
                findings.append(
                    Finding("info", "rawavg-matches-t1", "FreeSurfer rawavg.mgz shares the T1 voxel grid")
                    if same
                    else Finding(
                        "warning",
                        "rawavg-differs",
                        "FreeSurfer rawavg.mgz does not share the T1 voxel grid; the reconstruction may come from another scan",
                    )
                )
    if subject.spec.id == "ds000248":
        findings.extend(_bids_checks(subject, t1_info.shape if t1_info else None))
    return findings


def _bids_checks(subject: SubjectSource, t1_shape: tuple[int, ...] | None) -> list[Finding]:
    findings: list[Finding] = []
    base = subject.dataset_dir
    participants = base / "participants.tsv"
    if participants.is_file():
        # ds000248's participants.tsv starts with a UTF-8 byte-order mark.
        with participants.open(newline="", encoding="utf-8-sig") as f:
            ids = {row.get("participant_id") for row in csv.DictReader(f, delimiter="\t")}
        if subject.subject_id not in ids:
            findings.append(Finding("error", "not-in-participants", f"{subject.subject_id} is missing from participants.tsv"))
    else:
        findings.append(Finding("warning", "no-participants", "participants.tsv is missing"))
    if not (base / "dataset_description.json").is_file():
        findings.append(Finding("error", "no-dataset-description", "dataset_description.json is missing"))
    sub_dir = base / subject.subject_id
    stray = [p.name for p in sub_dir.rglob("*") if p.is_file() and not p.name.startswith(f"{subject.subject_id}_")]
    if stray:
        findings.append(Finding("warning", "bids-entity-mismatch", f"files without the subject entity: {', '.join(stray[:3])}"))
    sidecar = sub_dir / "anat" / f"{subject.subject_id}_T1w.json"
    if sidecar.is_file() and t1_shape is not None:
        try:
            landmarks = json.loads(sidecar.read_text(encoding="utf-8")).get("AnatomicalLandmarkCoordinates", {})
        except ValueError:
            findings.append(Finding("error", "invalid-sidecar", f"{sidecar.name} is not valid JSON"))
        else:
            for name, voxel in landmarks.items():
                inside = len(voxel) == 3 and all(0 <= float(v) < n for v, n in zip(voxel, t1_shape[:3], strict=True))
                if not inside:
                    findings.append(Finding("error", "landmark-outside-volume", f"landmark {name} lies outside the T1 voxel grid"))
            if landmarks and not any(f.code == "landmark-outside-volume" for f in findings):
                findings.append(
                    Finding("info", "landmarks", f"T1w sidecar landmarks inside the volume: {', '.join(sorted(landmarks))}")
                )
    meg_sidecars = sorted((sub_dir / "meg").glob("*_meg.json")) if (sub_dir / "meg").is_dir() else []
    for meg_json in meg_sidecars:
        try:
            meta = json.loads(meg_json.read_text(encoding="utf-8"))
        except ValueError:
            findings.append(Finding("error", "invalid-sidecar", f"{meg_json.name} is not valid JSON"))
            continue
        eeg = meta.get("EEGChannelCount")
        rate = meta.get("SamplingFrequency")
        if isinstance(eeg, int) and isinstance(rate, (int, float)) and np.isfinite(rate):
            findings.append(Finding("info", "eeg-recording", f"{meg_json.name}: {eeg} EEG channels at {rate} Hz"))
    return findings
