"""Anatomy asset contract v1 models mirroring
packages/protocol/schemas/anatomy-asset.v1.schema.json.

The JSON Schema is canonical. Parity with the TypeScript validator is enforced
by the shared fixtures in packages/protocol/fixtures/anatomy-v1/
(tests/test_anatomy_contract.py). Rules JSON Schema cannot express live in
`semantic_issue`, exactly as in packages/protocol/src/anatomy.ts.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)
from pydantic.alias_generators import to_camel

from neuro_engine.protocol.v2 import (
    MAX_SAFE_INTEGER,
    JsonInteger,
    ProtocolError,
    decode_json,
)

SCHEMA_VERSION: Literal[1] = 1

AssetId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
AssetFileName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
AnatomyText = Annotated[str, StringConstraints(min_length=1, max_length=128)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
AnatomySlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$")]
Count = Annotated[int, JsonInteger, Field(ge=0, le=MAX_SAFE_INTEGER)]
VertexCount = Annotated[int, JsonInteger, Field(ge=4, le=2_000_000)]
TriangleCount = Annotated[int, JsonInteger, Field(ge=4, le=4_000_000)]
Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]
Matrix4 = Annotated[list[float], Field(min_length=16, max_length=16)]
Hemisphere = Literal["lh", "rh"]
SurfaceKind = Literal["pial", "white", "inflated"]
AnatomyKind = Literal["template", "reference-subject", "personal"]
CoordinateFrame = Literal["freesurfer-surface-ras", "scanner-ras", "mni305-ras"]
AcquisitionSource = Literal["sidecar", "dataset-readme", "site-documentation", "user-declared", "not-applicable"]
Rgba = Annotated[
    list[Annotated[int, JsonInteger, Field(ge=0, le=255)]],
    Field(min_length=4, max_length=4),
]

# Float32 positions may differ from the float64 bounds by rounding (mm).
BOUNDS_TOLERANCE_MM = 1e-3


class _Doc(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        # Non-finite values are rejected by `semantic_issue` (parity with TypeScript).
        allow_inf_nan=True,
    )


class SubjectRef(_Doc):
    dataset_id: AnatomySlug
    dataset_version: AnatomyText
    subject_id: AnatomyText
    session_id: AnatomyText | None
    display_name: AnatomyText


class MriAcquisition(_Doc):
    field_strength_tesla: Annotated[float, Field(gt=0, le=20)] | None
    sequence: AnatomyText | None
    scanner: AnatomyText | None
    source: AcquisitionSource


class CoordinateTransform(_Doc):
    from_: CoordinateFrame = Field(alias="from")
    to: CoordinateFrame
    matrix: Matrix4
    units: Literal["mm"]
    source: AnatomyText


class BufferRef(_Doc):
    file: AssetFileName
    dtype: Literal["float32", "uint32", "int32"]
    byte_length: Count
    sha256: Sha256


class Bounds(_Doc):
    min: Vec3
    max: Vec3


class SurfaceMesh(_Doc):
    hemisphere: Hemisphere
    surface: SurfaceKind
    vertex_count: VertexCount
    triangle_count: TriangleCount
    positions: BufferRef
    indices: BufferRef
    bounds_mm: Bounds


class ParcellationLabel(_Doc):
    index: Count
    name: AnatomyText
    rgba: Rgba


class Parcellation(_Doc):
    atlas: AnatomySlug
    description: AnatomyText
    hemisphere: Hemisphere
    vertex_count: VertexCount
    labels: Annotated[list[ParcellationLabel], Field(min_length=1, max_length=1000)]
    vertex_labels: BufferRef


class SourceFile(_Doc):
    path: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9._/+-]{0,255}$")]
    bytes: Count
    sha256: Sha256


class ToolVersion(_Doc):
    name: AnatomyText
    version: AnatomyText


class AssetProvenance(_Doc):
    pipeline: Literal["neuro-engine.anatomy.prepare"]
    pipeline_version: AnatomyText
    prepared_at_utc: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]
    tools: Annotated[list[ToolVersion], Field(max_length=16)]
    sources: Annotated[list[SourceFile], Field(min_length=1, max_length=256)]


class DataLicense(_Doc):
    id: AnatomyText
    url: Annotated[str, StringConstraints(pattern=r"^https://[^\s]{1,500}$")]
    attribution: LongText


class AnatomyAsset(_Doc):
    type: Literal["anatomy.asset"]
    schema_version: Literal[1]
    asset_id: AssetId
    subject: SubjectRef
    anatomy_kind: AnatomyKind
    acquisition: MriAcquisition
    coordinate_frame: Literal["freesurfer-surface-ras"]
    units: Literal["mm"]
    transforms: Annotated[list[CoordinateTransform], Field(max_length=8)]
    surfaces: Annotated[list[SurfaceMesh], Field(min_length=1, max_length=6)]
    parcellations: Annotated[list[Parcellation], Field(max_length=16)]
    provenance: AssetProvenance
    license: DataLicense

    def buffer_files(self) -> set[str]:
        files = {s.positions.file for s in self.surfaces} | {s.indices.file for s in self.surfaces}
        return files | {p.vertex_labels.file for p in self.parcellations}


class AssetSummary(_Doc):
    asset_id: AssetId
    subject: SubjectRef
    anatomy_kind: AnatomyKind
    surfaces: Annotated[list[SurfaceKind], Field(min_length=1, max_length=3)]
    atlases: Annotated[list[AnatomySlug], Field(max_length=16)]
    license_id: AnatomyText


class AnatomyCatalog(_Doc):
    type: Literal["anatomy.catalog"]
    schema_version: Literal[1]
    default_asset_id: AssetId | None
    assets: Annotated[list[AssetSummary], Field(max_length=256)]


AnatomyDocument = Annotated[AnatomyAsset | AnatomyCatalog, Field(discriminator="type")]
_DOCUMENT = TypeAdapter[AnatomyAsset | AnatomyCatalog](AnatomyDocument)


def _finite(values: list[float]) -> bool:
    return all(math.isfinite(v) for v in values)


def _surface_issue(surface: SurfaceMesh, path: str) -> str | None:
    if surface.positions.dtype != "float32":
        return f"{path}/positions/dtype must be float32"
    if surface.indices.dtype != "uint32":
        return f"{path}/indices/dtype must be uint32"
    if surface.positions.byte_length != surface.vertex_count * 12:
        return f"{path}/positions/byteLength must be 12 * vertexCount"
    if surface.indices.byte_length != surface.triangle_count * 12:
        return f"{path}/indices/byteLength must be 12 * triangleCount"
    if not _finite(surface.bounds_mm.min) or not _finite(surface.bounds_mm.max):
        return f"{path}/boundsMm must be finite"
    if any(lo > hi for lo, hi in zip(surface.bounds_mm.min, surface.bounds_mm.max, strict=True)):
        return f"{path}/boundsMm/min must not exceed max"
    return None


def _parcellation_issue(parcellation: Parcellation, path: str, vertex_counts: dict[str, int]) -> str | None:
    if parcellation.vertex_labels.dtype != "int32":
        return f"{path}/vertexLabels/dtype must be int32"
    if parcellation.vertex_labels.byte_length != parcellation.vertex_count * 4:
        return f"{path}/vertexLabels/byteLength must be 4 * vertexCount"
    surface_count = vertex_counts.get(parcellation.hemisphere)
    if surface_count is None:
        return f"{path} labels hemisphere {parcellation.hemisphere}, which has no surface"
    if surface_count != parcellation.vertex_count:
        return f"{path}/vertexCount must equal the {parcellation.hemisphere} surface vertexCount {surface_count}"
    seen: set[int] = set()
    for position, label in enumerate(parcellation.labels):
        if label.index in seen:
            return f"{path}/labels/{position}/index duplicates an earlier label"
        seen.add(label.index)
    return None


def _asset_issue(asset: AnatomyAsset) -> str | None:
    files: set[str] = set()

    def claim(file: str, path: str) -> str | None:
        if file in files:
            return f"{path} reuses file {file}"
        files.add(file)
        return None

    seen: set[str] = set()
    vertex_counts: dict[str, int] = {}
    for position, surface in enumerate(asset.surfaces):
        path = f"/surfaces/{position}"
        key = f"{surface.hemisphere}.{surface.surface}"
        if key in seen:
            return f"{path} duplicates {key}"
        seen.add(key)
        known = vertex_counts.get(surface.hemisphere)
        if known is not None and known != surface.vertex_count:
            return f"{path}/vertexCount differs from another {surface.hemisphere} surface (vertices must correspond)"
        vertex_counts[surface.hemisphere] = surface.vertex_count
        issue = (
            _surface_issue(surface, path)
            or claim(surface.positions.file, f"{path}/positions")
            or claim(surface.indices.file, f"{path}/indices")
        )
        if issue:
            return issue
    atlases: set[str] = set()
    for position, parcellation in enumerate(asset.parcellations):
        path = f"/parcellations/{position}"
        key = f"{parcellation.hemisphere}.{parcellation.atlas}"
        if key in atlases:
            return f"{path} duplicates {key}"
        atlases.add(key)
        issue = _parcellation_issue(parcellation, path, vertex_counts) or claim(
            parcellation.vertex_labels.file, f"{path}/vertexLabels"
        )
        if issue:
            return issue
    for position, transform in enumerate(asset.transforms):
        path = f"/transforms/{position}"
        if transform.from_ != asset.coordinate_frame:
            return f"{path}/from must be the asset coordinateFrame"
        if transform.to == transform.from_:
            return f"{path}/to must differ from from"
        if not _finite(transform.matrix):
            return f"{path}/matrix must be finite"
        if transform.matrix[12:] != [0, 0, 0, 1]:
            return f"{path}/matrix last row must be [0, 0, 0, 1]"
    return None


def _catalog_issue(catalog: AnatomyCatalog) -> str | None:
    ids: set[str] = set()
    for position, summary in enumerate(catalog.assets):
        if summary.asset_id in ids:
            return f"/assets/{position}/assetId duplicates an earlier asset"
        ids.add(summary.asset_id)
        if len(set(summary.surfaces)) != len(summary.surfaces):
            return f"/assets/{position}/surfaces contains duplicates"
    if catalog.default_asset_id is not None and catalog.default_asset_id not in ids:
        return "/defaultAssetId is not one of the listed assets"
    return None


def semantic_issue(document: AnatomyAsset | AnatomyCatalog) -> str | None:
    return _asset_issue(document) if isinstance(document, AnatomyAsset) else _catalog_issue(document)


def _describe(error: ValidationError) -> str:
    first = error.errors(include_input=False, include_url=False)[0]
    return "/" + "/".join(str(part) for part in first["loc"]) + f" {first['msg']}"


def validate_document(value: Any) -> AnatomyAsset | AnatomyCatalog:
    """Validate a decoded JSON value. Raises ProtocolError."""
    if isinstance(value, dict):
        version = value.get("schemaVersion")
        if type(version) in (int, float) and version != SCHEMA_VERSION:
            raise ProtocolError(
                "unsupported-version", f"schemaVersion {version} is not supported (expected {SCHEMA_VERSION})"
            )
    try:
        document = _DOCUMENT.validate_python(value, by_alias=True, by_name=False)
    except ValidationError as exc:
        raise ProtocolError("schema", _describe(exc)) from None
    issue = semantic_issue(document)
    if issue is not None:
        raise ProtocolError("semantic", issue)
    return document


def parse_document(raw: str | bytes) -> AnatomyAsset | AnatomyCatalog:
    """Parse and validate raw JSON text. Raises ProtocolError."""
    try:
        value = decode_json(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("json", "document is not valid JSON") from None
    return validate_document(value)


def to_wire_dict(document: AnatomyAsset | AnatomyCatalog) -> dict[str, Any]:
    """Serialize after semantic validation. Raises ProtocolError."""
    issue = semantic_issue(document)
    if issue is not None:
        raise ProtocolError("semantic", issue)
    return document.model_dump(mode="json")
