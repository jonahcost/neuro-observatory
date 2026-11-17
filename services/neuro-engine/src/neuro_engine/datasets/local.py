"""Local imports: a personal T1 volume and/or an existing FreeSurfer subject directory.

Source paths and original file names are not recorded: they often contain a
person's name. Files are copied into `<root>/raw/local/1/` and never overwritten.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from neuro_engine import __version__
from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.anatomy.surfaces import HEMISPHERES, SURFACE_KINDS, read_surface
from neuro_engine.anatomy.volumes import check_mri, volume_suffix
from neuro_engine.datasets.catalog import get_dataset
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import sha256_file
from neuro_engine.datasets.provenance import (
    AcquiredFile,
    DeclaredAcquisition,
    ToolVersion,
    new_record,
    read_record,
    write_record,
)
from neuro_engine.datasets.storage import DataRoot, private_mkdir

_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
FREESURFER_REQUIRED = tuple(f"surf/{h}.{k}" for h in HEMISPHERES for k in SURFACE_KINDS)
FREESURFER_OPTIONAL = (
    *(f"label/{h}.{a}.annot" for h in HEMISPHERES for a in ("aparc", "aparc.a2009s", "aparc.DKTatlas")),
    "mri/orig.mgz",
    "mri/T1.mgz",
    "mri/rawavg.mgz",
    "scripts/build-stamp.txt",
)


def check_label(label: str) -> str:
    if not _LABEL.match(label):
        raise DatasetError(
            "invalid-subject-label",
            f"'{label}' is not a valid local subject label",
            "use 1-32 lowercase letters, digits or hyphens, e.g. 'me' or 'self-2026'; avoid real names",
        )
    return label


def _copy_new(source: Path, destination: Path, *, validate: Callable[[Path], None] | None = None) -> tuple[int, str]:
    """Copy one stable source snapshot, validate/hash staging, then publish without overwrite."""
    private_mkdir(destination.parent)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".stage-{destination.stem}.",
        suffix="".join(destination.suffixes),
        dir=destination.parent,
    )
    tmp = Path(tmp_name)
    try:
        with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        if validate is not None:
            validate(tmp)
        digest = sha256_file(tmp)
        size = tmp.stat().st_size
        if destination.is_symlink():
            raise DatasetError("unsafe-path", f"refusing symlinked destination {destination.name}")
        if destination.is_file():
            if sha256_file(destination) != digest:
                raise DatasetError(
                    "existing-file-mismatch",
                    f"a different {destination.name} is already imported for this subject",
                    "imported files are never overwritten; use a new subject label",
                )
            if os.name == "posix":
                destination.chmod(0o600)
            return size, digest
        try:
            os.link(tmp, destination)
        except FileExistsError:
            if destination.is_symlink():
                raise DatasetError("unsafe-path", f"destination {destination.name} became a symlink") from None
            if sha256_file(destination) != digest:
                raise DatasetError(
                    "existing-file-mismatch",
                    f"a different {destination.name} was imported concurrently",
                    "use a new subject label",
                ) from None
        if os.name == "posix":
            destination.chmod(0o600)
        return size, digest
    finally:
        tmp.unlink(missing_ok=True)


def _validate_imported_mri(path: Path, *, assume_mm: bool = False) -> None:
    try:
        check = check_mri(path, read_data=True, assume_mm=assume_mm)
    except AnatomyError as exc:
        raise DatasetError("invalid-volume", exc.message, "provide a NIfTI (.nii/.nii.gz) or FreeSurfer (.mgz) T1 volume") from None
    errors = [f.message for f in check.findings if f.level == "error"]
    if errors:
        raise DatasetError("invalid-volume", errors[0])


def _validate_imported_surface(path: Path, relative: str) -> None:
    hemi, kind = relative.removeprefix("surf/").split(".")
    try:
        read_surface(path, hemi, kind)  # type: ignore[arg-type]
    except AnatomyError as exc:
        raise DatasetError("invalid-surface", exc.message) from None


def _update_record(root: DataRoot, files: list[AcquiredFile], label: str, declared: DeclaredAcquisition | None) -> None:
    spec = get_dataset("local")
    record = read_record(root, spec.id, spec.version) or new_record(
        spec, tools=[ToolVersion(name="neuro-engine", version=__version__)]
    )
    record.upsert_files(files)
    if declared is not None:
        record.declared_acquisition[label] = declared
    write_record(root, record)


def import_mri(
    root: DataRoot,
    source: Path,
    label: str,
    *,
    field_strength_tesla: float | None = None,
    sequence: str | None = None,
    scanner: str | None = None,
    assume_mm: bool = False,
) -> Path:
    check_label(label)
    if field_strength_tesla is not None and not 0 < field_strength_tesla <= 20:
        raise DatasetError("invalid-field-strength", "field strength must be in (0, 20] tesla")
    _validate_imported_mri(source, assume_mm=assume_mm)
    spec = get_dataset("local")
    root.prepare_for_writing()
    relative = f"mri/{label}/T1w{volume_suffix(source)}"
    destination = root.raw(spec.id, spec.version) / relative
    existing = [p for p in destination.parent.glob("T1w.*")] if destination.parent.is_dir() else []
    if any(p.name != destination.name for p in existing):
        raise DatasetError("existing-file-mismatch", f"subject '{label}' already has a T1 in another format", "use a new label")
    size, digest = _copy_new(source, destination, validate=lambda path: _validate_imported_mri(path, assume_mm=assume_mm))
    _update_record(
        root,
        [AcquiredFile(path=relative, bytes=size, sha256=digest)],
        label,
        DeclaredAcquisition(
            field_strength_tesla=field_strength_tesla,
            sequence=sequence,
            scanner=scanner,
            spatial_units_assumed_mm=assume_mm,
        ),
    )
    return destination


def import_freesurfer(
    root: DataRoot,
    subject_dir: Path,
    label: str,
    *,
    tool_name: str | None = None,
    tool_version: str | None = None,
    command_summary: str | None = None,
    qc_status: str | None = None,
    qc_notes: str = "",
) -> Path:
    """Copy the surfaces (required), annotations and volumes (optional) of one recon-all subject."""
    check_label(label)
    if not tool_name or not tool_version or not command_summary or qc_status not in ("passed", "failed", "not-reviewed"):
        raise DatasetError(
            "missing-reconstruction-metadata",
            "FreeSurfer imports require tool name/version, a privacy-safe command summary and QC status",
            "provide --tool, --tool-version, --command-summary and --qc-status",
        )
    local_base = root.raw("local", get_dataset("local").version)
    if not any((local_base / "mri" / label).glob("T1w.*")):
        raise DatasetError(
            "missing-reconstruction-input",
            f"local/{label} has no imported source T1",
            "import the MRI with the same label before importing its reconstruction",
        )
    from neuro_engine.datasets.reconstruction import verify_acquired_input
    from neuro_engine.datasets.subjects import resolve_subject

    verify_acquired_input(root, resolve_subject(root, f"local/{label}"))
    missing = [p for p in FREESURFER_REQUIRED if not (subject_dir / p).is_file()]
    if missing:
        raise DatasetError(
            "incomplete-freesurfer-subject",
            f"the FreeSurfer subject directory lacks {', '.join(missing)}",
            "point at the subject directory produced by recon-all (containing surf/, label/, mri/)",
        )
    for relative in FREESURFER_REQUIRED:
        hemi, kind = relative.removeprefix("surf/").split(".")
        try:
            read_surface(subject_dir / relative, hemi, kind)  # type: ignore[arg-type]
        except AnatomyError as exc:
            raise DatasetError("invalid-surface", exc.message) from None
    spec = get_dataset("local")
    root.prepare_for_writing()
    base = root.raw(spec.id, spec.version)
    acquired: list[AcquiredFile] = []
    for relative in (*FREESURFER_REQUIRED, *FREESURFER_OPTIONAL):
        source = subject_dir / relative
        if not source.is_file():
            continue
        stored = f"freesurfer/{label}/{relative}"
        validator = (lambda path, rel=relative: _validate_imported_surface(path, rel)) if relative in FREESURFER_REQUIRED else None
        size, digest = _copy_new(source, base / stored, validate=validator)
        acquired.append(AcquiredFile(path=stored, bytes=size, sha256=digest))
    _update_record(root, acquired, label, None)
    imported = base / "freesurfer" / label
    from neuro_engine.datasets.reconstruction import write_reconstruction_record

    write_reconstruction_record(
        root,
        resolve_subject(root, f"local/{label}"),
        tool_name=tool_name,
        tool_version=tool_version,
        command_summary=command_summary,
        qc_status=qc_status,  # type: ignore[arg-type]
        qc_notes=qc_notes,
    )
    return imported
