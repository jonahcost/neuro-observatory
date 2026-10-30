"""FreeSurfer cortical surfaces and annotation (parcellation) files, read with nibabel."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from nibabel.freesurfer import io as fsio
from numpy.typing import NDArray

from neuro_engine.anatomy.errors import AnatomyError

Hemisphere = Literal["lh", "rh"]
SurfaceKind = Literal["pial", "white", "inflated"]
HEMISPHERES: tuple[Hemisphere, ...] = ("lh", "rh")
SURFACE_KINDS: tuple[SurfaceKind, ...] = ("pial", "white", "inflated")
MAX_VERTICES = 2_000_000
MAX_TRIANGLES = 4_000_000


@dataclass(frozen=True, slots=True)
class CorticalSurface:
    """One hemisphere surface in FreeSurfer surface RAS, millimetres.

    `vertices` keeps FreeSurfer's vertex order (shared by all surfaces of the
    hemisphere); `faces` are FreeSurfer's triangles, unchanged.
    """

    hemisphere: Hemisphere
    kind: SurfaceKind
    vertices: NDArray[np.float64]
    faces: NDArray[np.int64]
    cras: NDArray[np.float64] | None

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.faces.shape[0])

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)


@dataclass(frozen=True, slots=True)
class ParcellationLabel:
    index: int
    name: str
    rgba: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Parcellation:
    """Atlas labels per vertex: an index into `labels`, or -1 when unlabelled."""

    atlas: str
    hemisphere: Hemisphere
    vertex_labels: NDArray[np.int32]
    labels: tuple[ParcellationLabel, ...]


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise AnatomyError("missing-file", f"{path.name} not found")


def read_surface(path: Path, hemisphere: Hemisphere, kind: SurfaceKind) -> CorticalSurface:
    _require_file(path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            vertices, faces, metadata = fsio.read_geometry(str(path), read_metadata=True)
    except Exception as exc:  # nibabel raises ValueError/EOFError/struct errors for corrupt files
        raise AnatomyError(
            "unreadable-surface", f"{path.name}: not a readable FreeSurfer triangle surface ({type(exc).__name__})"
        ) from exc
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise AnatomyError("invalid-surface", f"{path.name}: vertices and faces must be N x 3")
    if not 4 <= vertices.shape[0] <= MAX_VERTICES or not 4 <= faces.shape[0] <= MAX_TRIANGLES:
        raise AnatomyError("invalid-surface", f"{path.name}: vertex or triangle count out of range")
    if not np.all(np.isfinite(vertices)):
        raise AnatomyError("invalid-surface", f"{path.name}: non-finite vertex coordinates")
    if faces.min() < 0 or faces.max() >= vertices.shape[0]:
        raise AnatomyError("invalid-surface", f"{path.name}: triangle references a vertex out of range")
    if np.any((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2])):
        raise AnatomyError("invalid-surface", f"{path.name}: degenerate triangle (repeated vertex)")
    cras = metadata.get("cras") if metadata else None
    return CorticalSurface(
        hemisphere=hemisphere,
        kind=kind,
        vertices=vertices,
        faces=faces,
        cras=None if cras is None else np.asarray(cras, dtype=np.float64),
    )


def signed_volume_mm3(surface: CorticalSurface) -> float:
    """Signed enclosed volume; positive when triangles wind counter-clockwise seen from outside."""
    a, b, c = (surface.vertices[surface.faces[:, i]] for i in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def read_parcellation(path: Path, atlas: str, hemisphere: Hemisphere, vertex_count: int) -> Parcellation:
    _require_file(path)
    try:
        labels, ctab, names = fsio.read_annot(str(path))
    except Exception as exc:
        raise AnatomyError(
            "unreadable-annotation", f"{path.name}: not a readable FreeSurfer annotation ({type(exc).__name__})"
        ) from exc
    labels = np.asarray(labels)
    if labels.shape != (vertex_count,):
        raise AnatomyError(
            "invalid-annotation", f"{path.name}: {labels.shape[0]} labels for a {vertex_count}-vertex surface"
        )
    ctab = np.asarray(ctab)
    if ctab.ndim != 2 or ctab.shape[0] != len(names) or ctab.shape[1] < 4:
        raise AnatomyError("invalid-annotation", f"{path.name}: colour table does not match label names")
    if labels.min() < -1 or labels.max() >= len(names):
        raise AnatomyError("invalid-annotation", f"{path.name}: vertex label outside the colour table")
    table = tuple(
        ParcellationLabel(
            index=i,
            name=(name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name))[:128] or f"label-{i}",
            # FreeSurfer stores transparency; alpha = 255 - transparency.
            rgba=(int(row[0]) & 255, int(row[1]) & 255, int(row[2]) & 255, 255 - (int(row[3]) & 255)),
        )
        for i, (name, row) in enumerate(zip(names, ctab, strict=True))
    )
    return Parcellation(atlas=atlas, hemisphere=hemisphere, vertex_labels=labels.astype(np.int32), labels=table)
