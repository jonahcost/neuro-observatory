"""Versioned provenance for externally reconstructed FreeSurfer subjects."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
from pydantic.alias_generators import to_camel

from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import sha256_file
from neuro_engine.datasets.provenance import read_record
from neuro_engine.datasets.storage import (
    DataRoot,
    ensure_contained,
    file_lock,
    private_mkdir,
)
from neuro_engine.datasets.subjects import SubjectSource

RECONSTRUCTION_RECORD_VERSION: Literal[1] = 1
RelativePath = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9._/+-]{0,255}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


class ReconstructionFile(_Record):
    path: RelativePath
    bytes: Annotated[int, Field(ge=0)]
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def _relative(cls, value: str) -> str:
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise ValueError("path must be relative without empty, '.' or '..' segments")
        return value


class ReconstructionRecord(_Record):
    record_version: Literal[1] = RECONSTRUCTION_RECORD_VERSION
    subject_key: str
    dataset_id: str
    dataset_version: str
    input: ReconstructionFile
    tool_name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    tool_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    command_summary: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    qc_status: Literal["passed", "failed", "not-reviewed"]
    qc_notes: Annotated[str, StringConstraints(max_length=2000)] = ""
    created_at_utc: str
    outputs: Annotated[list[ReconstructionFile], Field(min_length=1, max_length=256)]

    def output_index(self) -> dict[str, ReconstructionFile]:
        return {entry.path: entry for entry in self.outputs}


def _file(root: DataRoot, path: Path) -> ReconstructionFile:
    contained = ensure_contained(root.path, path)
    return ReconstructionFile(
        path=contained.relative_to(root.path.resolve()).as_posix(),
        bytes=contained.stat().st_size,
        sha256=sha256_file(contained),
    )


def verify_acquired_input(root: DataRoot, subject: SubjectSource) -> ReconstructionFile:
    if subject.t1 is None:
        raise DatasetError("missing-reconstruction-input", f"{subject.key} has no source T1")
    acquisition = read_record(root, subject.spec.id, subject.spec.version)
    if acquisition is None:
        raise DatasetError("missing-provenance", f"{subject.spec.id} {subject.spec.version} has no acquisition record")
    resolved = ensure_contained(root.path, subject.t1)
    base = root.raw(subject.spec.id, subject.spec.version).resolve()
    if not resolved.is_relative_to(base):
        raise DatasetError("source-provenance-mismatch", f"{subject.key}: source T1 is outside its acquired dataset")
    relative = resolved.relative_to(base).as_posix()
    expected = acquisition.file_index().get(relative)
    actual = _file(root, resolved)
    if expected is None or expected.bytes != actual.bytes or expected.sha256 != actual.sha256:
        raise DatasetError("source-provenance-mismatch", f"{subject.key}: source T1 does not match acquisition provenance")
    return actual


def write_reconstruction_record(
    root: DataRoot,
    subject: SubjectSource,
    *,
    tool_name: str,
    tool_version: str,
    command_summary: str,
    qc_status: Literal["passed", "failed", "not-reviewed"],
    qc_notes: str = "",
) -> Path:
    if subject.t1 is None or subject.freesurfer_dir is None:
        raise DatasetError(
            "incomplete-reconstruction-provenance",
            f"{subject.key} needs both its source T1 and FreeSurfer output before reconstruction provenance can be recorded",
        )
    outputs = sorted(path for path in subject.freesurfer_dir.rglob("*") if path.is_file() and path.name != "reconstruction.json")
    if not outputs:
        raise DatasetError("incomplete-reconstruction-provenance", f"{subject.key} has no reconstruction outputs")
    acquired_input = verify_acquired_input(root, subject)
    record = ReconstructionRecord(
        subject_key=subject.key,
        dataset_id=subject.spec.id,
        dataset_version=subject.spec.version,
        input=acquired_input,
        tool_name=tool_name,
        tool_version=tool_version,
        command_summary=command_summary,
        qc_status=qc_status,
        qc_notes=qc_notes,
        created_at_utc=_utc_now(),
        outputs=[_file(root, path) for path in outputs],
    )
    path = root.reconstruction_record(subject.spec.id, subject.spec.version, subject.subject_id)
    root.prepare_for_writing()
    ensure_contained(root.path, path)
    private_mkdir(path.parent)
    with file_lock(path):
        descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(record.model_dump(mode="json"), indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            if os.name == "posix":
                path.chmod(0o600)
        finally:
            tmp.unlink(missing_ok=True)
    return path


def read_reconstruction_record(root: DataRoot, subject: SubjectSource) -> ReconstructionRecord | None:
    path = root.reconstruction_record(subject.spec.id, subject.spec.version, subject.subject_id)
    if not path.is_file():
        return None
    try:
        record = ReconstructionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        raise DatasetError("corrupt-reconstruction-provenance", f"reconstruction record for {subject.key} is unreadable") from None
    if (
        record.subject_key != subject.key
        or record.dataset_id != subject.spec.id
        or record.dataset_version != subject.spec.version
    ):
        raise DatasetError("corrupt-reconstruction-provenance", f"reconstruction record identity does not match {subject.key}")
    return record


def verify_subject_source_provenance(
    root: DataRoot,
    subject: SubjectSource,
    source_paths: list[Path],
) -> None:
    """Require source hashes to match acquisition and, where applicable, reconstruction provenance."""
    acquisition = read_record(root, subject.spec.id, subject.spec.version)
    if acquisition is None:
        raise DatasetError("missing-provenance", f"{subject.spec.id} {subject.spec.version} has no acquisition record")
    acquired = acquisition.file_index()
    dataset_base = root.raw(subject.spec.id, subject.spec.version).resolve()
    reconstruction_required = subject.spec.id == "local"
    for source in source_paths:
        resolved = ensure_contained(root.path, source)
        if resolved.is_relative_to(dataset_base):
            relative = resolved.relative_to(dataset_base).as_posix()
            entry = acquired.get(relative)
            if entry is None or entry.bytes != resolved.stat().st_size or entry.sha256 != sha256_file(resolved):
                raise DatasetError("source-provenance-mismatch", f"{subject.key}: {relative} does not match acquisition provenance")
        else:
            reconstruction_required = True

    if not reconstruction_required:
        return
    reconstruction = read_reconstruction_record(root, subject)
    if reconstruction is None:
        raise DatasetError(
            "missing-reconstruction-provenance",
            f"{subject.key} has no versioned reconstruction record",
            "record the reconstruction tool, command/configuration and visual QC before preparing anatomy",
        )
    if reconstruction.qc_status != "passed":
        raise DatasetError(
            "reconstruction-qc-incomplete",
            f"{subject.key} reconstruction QC status is {reconstruction.qc_status}",
            "complete visual QC and record qc-status passed before preparing anatomy",
        )
    expected_input = verify_acquired_input(root, subject)
    if reconstruction.input != expected_input:
        raise DatasetError("source-provenance-mismatch", f"{subject.key}: source T1 does not match reconstruction provenance")
    outputs = reconstruction.output_index()
    for source in source_paths:
        relative = ensure_contained(root.path, source).relative_to(root.path.resolve()).as_posix()
        expected = outputs.get(relative)
        actual = _file(root, source)
        if expected != actual:
            raise DatasetError("source-provenance-mismatch", f"{subject.key}: {relative} does not match reconstruction provenance")
