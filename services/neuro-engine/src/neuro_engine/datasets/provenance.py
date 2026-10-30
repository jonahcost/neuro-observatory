"""Acquisition provenance records: <root>/raw/<dataset>/<version>.acquisition.json."""

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

from neuro_engine.datasets.catalog import DatasetSpec
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import sha256_file
from neuro_engine.datasets.storage import (
    DataRoot,
    ensure_contained,
    file_lock,
    private_mkdir,
)

RECORD_VERSION: Literal[1] = 1
DatasetKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


class ToolVersion(_Record):
    name: str
    version: str


class AcquiredFile(_Record):
    path: Annotated[str, Field(pattern=r"^[A-Za-z0-9._/+-]{1,256}$")]
    bytes: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    upstream_checksum: str | None = None
    source_url: str | None = None

    @field_validator("path")
    @classmethod
    def _relative(cls, value: str) -> str:
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise ValueError("path must be relative without '.' or '..' segments")
        return value


class DeclaredAcquisition(_Record):
    field_strength_tesla: float | None = None
    sequence: str | None = None
    scanner: str | None = None
    spatial_units_assumed_mm: bool = False


class AcquisitionRecord(_Record):
    record_version: Literal[1] = RECORD_VERSION
    dataset_id: DatasetKey
    dataset_version: DatasetKey
    title: str
    doi: str | None
    homepage: str
    license_id: str
    license_url: str
    attribution: str
    license_accepted_at_utc: str | None = None
    method: str
    profile: str | None = None
    tools: list[ToolVersion] = Field(default_factory=list)
    created_at_utc: str
    updated_at_utc: str
    files: list[AcquiredFile] = Field(default_factory=list)
    declared_acquisition: dict[str, DeclaredAcquisition] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def file_index(self) -> dict[str, AcquiredFile]:
        return {f.path: f for f in self.files}

    def upsert_files(self, files: list[AcquiredFile]) -> None:
        merged = self.file_index()
        for f in files:
            merged[f.path] = f
        self.files = sorted(merged.values(), key=lambda f: f.path)


def new_record(spec: DatasetSpec, *, profile: str | None = None, tools: list[ToolVersion] | None = None) -> AcquisitionRecord:
    now = utc_now()
    return AcquisitionRecord(
        dataset_id=spec.id,
        dataset_version=spec.version,
        title=spec.title,
        doi=spec.doi,
        homepage=spec.homepage,
        license_id=spec.license.id,
        license_url=spec.license.url,
        attribution=spec.license.attribution,
        method=spec.method,
        profile=profile,
        tools=tools or [],
        created_at_utc=now,
        updated_at_utc=now,
        notes=list(spec.notes),
    )


def read_record(root: DataRoot, dataset_id: str, version: str) -> AcquisitionRecord | None:
    path = root.acquisition_record(dataset_id, version)
    if not path.is_file():
        return None
    try:
        record = AcquisitionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        raise DatasetError(
            "corrupt-provenance",
            f"provenance record for {dataset_id} {version} is unreadable",
            f"re-run 'neuro-engine datasets fetch {dataset_id}' to rebuild it",
        ) from None
    if record.dataset_id != dataset_id or record.dataset_version != version:
        raise DatasetError(
            "corrupt-provenance",
            f"provenance record for {dataset_id} {version} describes {record.dataset_id} {record.dataset_version}",
            "move the mismatched record aside and reacquire the dataset",
        )
    return record


def verify_record(root: DataRoot, record: AcquisitionRecord) -> list[str]:
    """Re-hash every recorded file. Returns problems; empty means all files match."""
    base = root.raw(record.dataset_id, record.dataset_version)
    problems: list[str] = []
    for entry in record.files:
        try:
            path = ensure_contained(base, base / entry.path)
        except DatasetError:
            problems.append(f"{entry.path}: escapes the dataset directory")
            continue
        if not path.is_file():
            problems.append(f"{entry.path}: missing")
        elif path.stat().st_size != entry.bytes:
            problems.append(f"{entry.path}: size {path.stat().st_size} differs from recorded {entry.bytes}")
        elif sha256_file(path) != entry.sha256:
            problems.append(f"{entry.path}: SHA-256 differs from the recorded value")
    return problems


def write_record(root: DataRoot, record: AcquisitionRecord) -> Path:
    root.prepare_for_writing()
    path = root.acquisition_record(record.dataset_id, record.dataset_version)
    ensure_contained(root.path, path)
    private_mkdir(path.parent)
    with file_lock(path):
        existing = read_record(root, record.dataset_id, record.dataset_version)
        if existing is not None:
            existing.upsert_files(record.files)
            existing.declared_acquisition.update(record.declared_acquisition)
            existing.notes = list(dict.fromkeys([*existing.notes, *record.notes]))
            existing.tools = list({(tool.name, tool.version): tool for tool in [*existing.tools, *record.tools]}.values())
            existing.profile = "full" if "full" in (existing.profile, record.profile) else (record.profile or existing.profile)
            existing.license_accepted_at_utc = existing.license_accepted_at_utc or record.license_accepted_at_utc
            record = existing
        record.updated_at_utc = utc_now()
        descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            os.chmod(descriptor, 0o600)
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
