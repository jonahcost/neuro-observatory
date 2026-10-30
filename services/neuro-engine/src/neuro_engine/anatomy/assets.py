"""Prepare and store app-ready anatomy assets (contract: anatomy-asset.v1).

An asset is a directory `<data>/assets/anatomy/<assetId>/` holding
`manifest.json` and little-endian binary buffers at full source resolution.
Coordinates are copied unchanged from the FreeSurfer surfaces (surface RAS, mm).
The asset ID hashes the source files, options and pipeline version, so an
unchanged input never produces a second asset. Assets are regenerable caches.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from numpy.typing import NDArray

from neuro_engine import __version__
from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.anatomy.surfaces import (
    HEMISPHERES,
    SURFACE_KINDS,
    CorticalSurface,
    Parcellation,
    read_parcellation,
    read_surface,
)
from neuro_engine.anatomy.transforms import (
    CoordinateTransform,
    fsaverage_surface_to_mni305,
    surface_ras_to_scanner_ras,
)
from neuro_engine.datasets.integrity import sha256_file
from neuro_engine.datasets.provenance import utc_now
from neuro_engine.datasets.storage import DataRoot
from neuro_engine.datasets.subjects import SubjectSource
from neuro_engine.protocol import anatomy_v1 as contract
from neuro_engine.protocol.v2 import ProtocolError

PIPELINE = "neuro-engine.anatomy.prepare"
PIPELINE_VERSION = "1"
MANIFEST = "manifest.json"
_ASSET_DIR = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
CRAS_SURFACE_TOLERANCE_MM = 1e-3

# FreeSurfer annotation file stem -> (contract atlas slug, description)
ATLASES: dict[str, tuple[str, str]] = {
    "aparc": ("aparc", "Desikan-Killiany cortical atlas (FreeSurfer aparc)"),
    "aparc.a2009s": ("aparc.a2009s", "Destrieux 2009 cortical atlas (FreeSurfer aparc.a2009s)"),
    "aparc.DKTatlas": ("aparc.dktatlas", "Desikan-Killiany-Tourville DKT40 atlas (FreeSurfer aparc.DKTatlas)"),
}


@dataclass(frozen=True, slots=True)
class PreparedAsset:
    asset_id: str
    path: Path
    created: bool


def _subject_slug(key: str) -> str:
    slug = re.sub(r"[^a-z0-9.-]+", "-", key.lower()).strip("-.")
    return slug[:80] or "subject"


def _source_files(subject: SubjectSource, surfaces: Sequence[str], atlases: Sequence[str] | None) -> tuple[dict[str, Path], list[str]]:
    """Ordered map of role -> path, and the annotation stems actually used."""
    fs = subject.freesurfer_dir
    if fs is None or not subject.has_surfaces:
        raise AnatomyError(
            "no-surfaces",
            f"{subject.key} has no complete FreeSurfer surface set; run recon-all or FastSurfer first "
            "(see pipelines/mri-reconstruction/README.md)",
        )
    files: dict[str, Path] = {}
    for hemi in HEMISPHERES:
        for kind in surfaces:
            files[f"surf.{hemi}.{kind}"] = fs / "surf" / f"{hemi}.{kind}"
    stems = list(ATLASES) if atlases is None else list(atlases)
    unknown = [s for s in stems if s not in ATLASES]
    if unknown:
        raise AnatomyError("unknown-atlas", f"unsupported atlas {unknown[0]}; choose from {', '.join(ATLASES)}")
    used = [s for s in stems if all((fs / "label" / f"{h}.{s}.annot").is_file() for h in HEMISPHERES)]
    if atlases is not None and len(used) != len(stems):
        missing = next(s for s in stems if s not in used)
        raise AnatomyError("missing-file", f"{missing} annotations are not present for both hemispheres")
    for stem in used:
        for hemi in HEMISPHERES:
            files[f"annot.{hemi}.{stem}"] = fs / "label" / f"{hemi}.{stem}.annot"
    orig = fs / "mri" / "orig.mgz"
    if orig.is_file():
        files["mri.orig"] = orig
    return files, used


def _asset_id(subject: SubjectSource, sources: dict[str, tuple[str, int, str]]) -> str:
    identity = {
        "pipeline": PIPELINE,
        "pipelineVersion": PIPELINE_VERSION,
        "subject": subject.key,
        "dataset": [subject.spec.id, subject.spec.version],
        "anatomyKind": subject.spec.anatomy_kind,
        "license": subject.spec.license.id,
        "acquisition": [
            subject.acquisition.field_strength_tesla,
            subject.acquisition.sequence,
            subject.acquisition.scanner,
            subject.acquisition.source,
        ],
        "sources": sorted(sources.items()),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"{_subject_slug(subject.key)}-{digest[:16]}"


def _buffer(directory: Path, name: str, array: NDArray, dtype: str) -> contract.BufferRef:
    data = np.ascontiguousarray(array, dtype=np.dtype(dtype).newbyteorder("<")).tobytes()
    (directory / name).write_bytes(data)
    return contract.BufferRef(file=name, dtype=dtype, byte_length=len(data), sha256=hashlib.sha256(data).hexdigest())  # type: ignore[arg-type]


def _shared_cras(surfaces: list[CorticalSurface]) -> NDArray[np.float64] | None:
    values = [s.cras for s in surfaces if s.cras is not None]
    if not values:
        return None
    if any(float(np.abs(v - values[0]).max()) > CRAS_SURFACE_TOLERANCE_MM for v in values):
        raise AnatomyError("inconsistent-transform", "surfaces disagree on c_ras; they are not from one reconstruction")
    return values[0]


def _transforms(subject: SubjectSource, surfaces: list[CorticalSurface], orig: Path | None) -> list[CoordinateTransform]:
    transforms: list[CoordinateTransform] = []
    scanner = surface_ras_to_scanner_ras(_shared_cras(surfaces), orig)
    if scanner is not None:
        transforms.append(scanner)
    if subject.spec.id == "fsaverage":
        transforms.append(fsaverage_surface_to_mni305())
    return transforms


def _tool_versions() -> list[contract.ToolVersion]:
    return [
        contract.ToolVersion(name="neuro-engine", version=__version__),
        contract.ToolVersion(name="nibabel", version=str(nib.__version__)),
        contract.ToolVersion(name="numpy", version=str(np.__version__)),
    ]


def prepare_asset(
    root: DataRoot,
    subject: SubjectSource,
    *,
    surfaces: Sequence[str] = SURFACE_KINDS,
    atlases: Sequence[str] | None = None,
    clock: Callable[[], str] = utc_now,
) -> PreparedAsset:
    """Convert a FreeSurfer subject into an anatomy asset. Idempotent per source content."""
    kinds = [k for k in SURFACE_KINDS if k in surfaces]
    if not kinds or len(kinds) != len(set(surfaces)):
        raise AnatomyError("invalid-option", f"surfaces must be a non-empty subset of {', '.join(SURFACE_KINDS)}")
    files, used_atlases = _source_files(subject, kinds, atlases)
    sources = {role: (subject.relative(path), path.stat().st_size, sha256_file(path)) for role, path in files.items()}
    asset_id = _asset_id(subject, sources)
    store = AssetStore(root)
    final = store.directory(asset_id)
    if (final / MANIFEST).is_file():
        problems = store.verify(asset_id)
        if problems:
            raise AnatomyError(
                "corrupt-asset", f"existing asset {asset_id} failed verification ({problems[0]}); delete it and prepare again"
            )
        return PreparedAsset(asset_id, final, created=False)

    meshes: list[CorticalSurface] = [
        read_surface(files[f"surf.{hemi}.{kind}"], hemi, kind) for hemi in HEMISPHERES for kind in kinds  # type: ignore[arg-type]
    ]
    for hemi in HEMISPHERES:
        counts = {m.vertex_count for m in meshes if m.hemisphere == hemi}
        if len(counts) != 1:
            raise AnatomyError("invalid-surface", f"{hemi} surfaces have different vertex counts; vertices must correspond")
    vertex_counts = {m.hemisphere: m.vertex_count for m in meshes}
    parcellations: list[Parcellation] = [
        read_parcellation(files[f"annot.{hemi}.{stem}"], stem, hemi, vertex_counts[hemi])  # type: ignore[arg-type]
        for stem in used_atlases
        for hemi in HEMISPHERES
    ]
    transforms = _transforms(subject, meshes, files.get("mri.orig"))

    root.prepare_for_writing()
    store.path.mkdir(parents=True, exist_ok=True)
    staging = store.path / f".staging-{asset_id}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        surface_docs = []
        for mesh in meshes:
            stem = f"{mesh.hemisphere}.{mesh.kind}"
            lo, hi = mesh.bounds()
            surface_docs.append(
                contract.SurfaceMesh(
                    hemisphere=mesh.hemisphere,
                    surface=mesh.kind,
                    vertex_count=mesh.vertex_count,
                    triangle_count=mesh.triangle_count,
                    positions=_buffer(staging, f"{stem}.positions.f32", mesh.vertices, "float32"),
                    indices=_buffer(staging, f"{stem}.indices.u32", mesh.faces, "uint32"),
                    bounds_mm=contract.Bounds(min=[float(v) for v in lo], max=[float(v) for v in hi]),
                )
            )
        parcellation_docs = []
        for parc in parcellations:
            slug, description = ATLASES[parc.atlas]
            parcellation_docs.append(
                contract.Parcellation(
                    atlas=slug,
                    description=description,
                    hemisphere=parc.hemisphere,
                    vertex_count=int(parc.vertex_labels.shape[0]),
                    labels=[contract.ParcellationLabel(index=lab.index, name=lab.name, rgba=list(lab.rgba)) for lab in parc.labels],
                    vertex_labels=_buffer(staging, f"{parc.hemisphere}.{slug}.labels.i32", parc.vertex_labels, "int32"),
                )
            )
        license_info = subject.spec.license
        asset = contract.AnatomyAsset(
            type="anatomy.asset",
            schema_version=1,
            asset_id=asset_id,
            subject=contract.SubjectRef(
                dataset_id=subject.spec.id,
                dataset_version=subject.spec.version,
                subject_id=subject.subject_id,
                session_id=subject.session_id,
                display_name=subject.display_name[:128],
            ),
            anatomy_kind=subject.spec.anatomy_kind,
            acquisition=contract.MriAcquisition(
                field_strength_tesla=subject.acquisition.field_strength_tesla,
                sequence=subject.acquisition.sequence,
                scanner=subject.acquisition.scanner,
                source=subject.acquisition.source,
            ),
            coordinate_frame="freesurfer-surface-ras",
            units="mm",
            transforms=[
                contract.CoordinateTransform.model_validate(
                    {"from": t.from_frame, "to": t.to_frame, "matrix": t.row_major(), "units": "mm", "source": t.source}
                )
                for t in transforms
            ],
            surfaces=surface_docs,
            parcellations=parcellation_docs,
            provenance=contract.AssetProvenance(
                pipeline=PIPELINE,
                pipeline_version=PIPELINE_VERSION,
                prepared_at_utc=clock(),
                tools=_tool_versions(),
                sources=[contract.SourceFile(path=p, bytes=b, sha256=h) for p, b, h in sources.values()],
            ),
            license=contract.DataLicense(id=license_info.id, url=license_info.url, attribution=license_info.attribution),
        )
        (staging / MANIFEST).write_text(json.dumps(contract.to_wire_dict(asset), indent=1) + "\n", encoding="utf-8")
        contract.parse_document((staging / MANIFEST).read_bytes())
        try:
            staging.rename(final)
        except OSError:
            if not (final / MANIFEST).is_file():
                raise
            shutil.rmtree(staging, ignore_errors=True)
            return PreparedAsset(asset_id, final, created=False)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PreparedAsset(asset_id, final, created=True)


class AssetStore:
    """Read-only view of prepared assets; the catalog is derived from the directory listing."""

    def __init__(self, root: DataRoot) -> None:
        self.root = root

    @property
    def path(self) -> Path:
        return self.root.anatomy_assets

    def directory(self, asset_id: str) -> Path:
        if not _ASSET_DIR.match(asset_id):
            raise AnatomyError("invalid-asset-id", "asset IDs contain only lowercase letters, digits, '.', '_' and '-'")
        return self.path / asset_id

    def manifest_bytes(self, asset_id: str) -> bytes:
        path = self.directory(asset_id) / MANIFEST
        if not path.is_file():
            raise AnatomyError("unknown-asset", f"no asset {asset_id}")
        return path.read_bytes()

    def manifest(self, asset_id: str) -> contract.AnatomyAsset:
        try:
            document = contract.parse_document(self.manifest_bytes(asset_id))
        except ProtocolError as exc:
            raise AnatomyError("invalid-manifest", f"asset {asset_id}: {exc}") from None
        if not isinstance(document, contract.AnatomyAsset) or document.asset_id != asset_id:
            raise AnatomyError("invalid-manifest", f"asset {asset_id}: manifest does not describe this asset")
        return document

    def buffer_path(self, asset_id: str, file_name: str) -> Path:
        """Only files listed in the manifest are served; the result stays inside the asset directory."""
        asset = self.manifest(asset_id)
        if file_name not in asset.buffer_files():
            raise AnatomyError("unknown-file", f"{file_name} is not part of asset {asset_id}")
        directory = self.directory(asset_id).resolve()
        path = (directory / file_name).resolve()
        if path.parent != directory or not path.is_file():
            raise AnatomyError("unknown-file", f"{file_name} is not part of asset {asset_id}")
        return path

    def _read_buffer(self, asset_id: str, ref: contract.BufferRef) -> NDArray:
        data = self.buffer_path(asset_id, ref.file).read_bytes()
        if len(data) != ref.byte_length or hashlib.sha256(data).hexdigest() != ref.sha256:
            raise AnatomyError("corrupt-asset", f"{ref.file} does not match the manifest; prepare the asset again")
        return np.frombuffer(data, dtype=np.dtype(ref.dtype).newbyteorder("<"))

    def load_mesh(self, asset_id: str, hemisphere: str, surface: str) -> tuple[NDArray[np.float32], NDArray[np.uint32]]:
        """Verified (N x 3 positions in surface RAS mm, M x 3 triangle indices)."""
        asset = self.manifest(asset_id)
        mesh = next((s for s in asset.surfaces if s.hemisphere == hemisphere and s.surface == surface), None)
        if mesh is None:
            raise AnatomyError("unknown-file", f"asset {asset_id} has no {hemisphere}.{surface} surface")
        return (
            self._read_buffer(asset_id, mesh.positions).reshape(-1, 3),
            self._read_buffer(asset_id, mesh.indices).reshape(-1, 3),
        )

    def assets(self) -> tuple[list[contract.AnatomyAsset], list[str]]:
        """Valid assets (sorted by subject, then preparation time) and problems with invalid ones."""
        if not self.path.is_dir():
            return [], []
        valid: list[contract.AnatomyAsset] = []
        problems: list[str] = []
        for entry in sorted(self.path.iterdir()):
            if not entry.is_dir() or not _ASSET_DIR.match(entry.name) or not (entry / MANIFEST).is_file():
                continue
            try:
                valid.append(self.manifest(entry.name))
            except AnatomyError as exc:
                problems.append(exc.message)
        valid.sort(key=lambda a: (a.subject.dataset_id, a.subject.subject_id, a.provenance.prepared_at_utc))
        return valid, problems

    def catalog(self) -> contract.AnatomyCatalog:
        assets, _ = self.assets()
        templates = [a for a in assets if a.anatomy_kind == "template"]
        default = (templates or assets)[-1].asset_id if assets else None
        return contract.AnatomyCatalog(
            type="anatomy.catalog",
            schema_version=1,
            default_asset_id=default,
            assets=[
                contract.AssetSummary(
                    asset_id=a.asset_id,
                    subject=a.subject,
                    anatomy_kind=a.anatomy_kind,
                    surfaces=sorted({s.surface for s in a.surfaces}, key=SURFACE_KINDS.index),
                    atlases=sorted({p.atlas for p in a.parcellations}),
                    license_id=a.license.id,
                )
                for a in assets
            ],
        )

    def verify(self, asset_id: str) -> list[str]:
        """Re-check every buffer against the manifest: size, SHA-256 and geometry/label ranges."""
        try:
            asset = self.manifest(asset_id)
        except AnatomyError as exc:
            return [exc.message]
        directory = self.directory(asset_id)
        problems: list[str] = []
        arrays: dict[str, NDArray] = {}
        for ref in [*(s.positions for s in asset.surfaces), *(s.indices for s in asset.surfaces), *(p.vertex_labels for p in asset.parcellations)]:
            path = directory / ref.file
            if not path.is_file():
                problems.append(f"{ref.file} is missing")
                continue
            data = path.read_bytes()
            if len(data) != ref.byte_length:
                problems.append(f"{ref.file} has {len(data)} bytes, manifest says {ref.byte_length}")
            elif hashlib.sha256(data).hexdigest() != ref.sha256:
                problems.append(f"{ref.file} SHA-256 does not match the manifest")
            else:
                arrays[ref.file] = np.frombuffer(data, dtype=np.dtype(ref.dtype).newbyteorder("<"))
        if problems:
            return problems
        for s in asset.surfaces:
            positions = arrays[s.positions.file].reshape(-1, 3)
            indices = arrays[s.indices.file]
            if not np.all(np.isfinite(positions)):
                problems.append(f"{s.hemisphere}.{s.surface}: non-finite positions")
            elif np.any(positions.min(axis=0) < np.array(s.bounds_mm.min) - contract.BOUNDS_TOLERANCE_MM) or np.any(
                positions.max(axis=0) > np.array(s.bounds_mm.max) + contract.BOUNDS_TOLERANCE_MM
            ):
                problems.append(f"{s.hemisphere}.{s.surface}: positions exceed boundsMm")
            if indices.size and int(indices.max()) >= s.vertex_count:
                problems.append(f"{s.hemisphere}.{s.surface}: triangle index out of range")
        for p in asset.parcellations:
            labels = arrays[p.vertex_labels.file]
            allowed = np.array(sorted({lab.index for lab in p.labels} | {-1}), dtype=np.int64)
            if not np.all(np.isin(labels, allowed)):
                problems.append(f"{p.hemisphere}.{p.atlas}: vertex label not in the label table")
        return problems
