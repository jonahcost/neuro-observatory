"""Synthetic neuroimaging files written at test time (never committed; no real data).

Surfaces are icospheres in genuine FreeSurfer binary format, so the production
readers are exercised end to end.
"""

from __future__ import annotations

import gzip
import io
import tarfile
from collections import OrderedDict
from pathlib import Path

import nibabel as nib
import numpy as np
from numpy.typing import NDArray

DEFAULT_CRAS = (1.5, -17.25, 18.0)
SURFACE_KINDS = ("pial", "white", "inflated")


def icosphere(subdivisions: int = 1) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Unit icosphere with outward, counter-clockwise triangles."""
    t = (1 + 5**0.5) / 2
    vertices = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]  # fmt: skip
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]  # fmt: skip
    verts = [np.array(v, dtype=np.float64) / np.linalg.norm(v) for v in vertices]

    def midpoint(cache: dict[tuple[int, int], int], a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in cache:
            m = verts[a] + verts[b]
            verts.append(m / np.linalg.norm(m))
            cache[key] = len(verts) - 1
        return cache[key]

    for _ in range(subdivisions):
        cache: dict[tuple[int, int], int] = {}
        new_faces = []
        for a, b, c in faces:
            ab, bc, ca = midpoint(cache, a, b), midpoint(cache, b, c), midpoint(cache, c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces
    return np.array(verts), np.array(faces, dtype=np.int64)


def volume_info(cras: tuple[float, float, float] = DEFAULT_CRAS) -> OrderedDict[str, object]:
    return OrderedDict(
        [
            ("head", np.array([2, 0, 20], dtype=np.int32)),
            ("valid", "1  # volume info valid"),
            ("filename", "orig.mgz"),
            ("volume", np.array([8, 8, 8], dtype=np.int64)),
            ("voxelsize", np.array([1.0, 1.0, 1.0])),
            ("xras", np.array([-1.0, 0.0, 0.0])),
            ("yras", np.array([0.0, 0.0, -1.0])),
            ("zras", np.array([0.0, 1.0, 0.0])),
            ("cras", np.array(cras, dtype=np.float64)),
        ]
    )


def surface_vertices(hemi: str, kind: str) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    unit, faces = icosphere(1)
    radius = {"pial": 30.0, "white": 27.0, "inflated": 34.0}[kind]
    centre = np.array([-35.0 if hemi == "lh" else 35.0, -10.0, 12.0])
    # Round to float32 so the source is exactly representable (as in real FreeSurfer files).
    return (unit * radius + centre).astype(np.float32).astype(np.float64), faces


def write_surface(path: Path, vertices: NDArray, faces: NDArray, cras: tuple[float, float, float] | None = DEFAULT_CRAS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.freesurfer.write_geometry(
        str(path), vertices, faces, create_stamp="created by neuro-engine tests (synthetic)",
        volume_info=volume_info(cras) if cras is not None else None,
    )  # fmt: skip


ANNOT_NAMES = ["unknown", "precentral", "postcentral"]
ANNOT_CTAB = np.array([[25, 5, 25, 0], [60, 20, 220, 0], [220, 20, 20, 0]], dtype=np.int32)


def write_annot(path: Path, vertex_count: int) -> NDArray[np.int32]:
    labels = (np.arange(vertex_count) % 3).astype(np.int32)
    labels[0] = -1
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.freesurfer.write_annot(str(path), labels, ANNOT_CTAB, ANNOT_NAMES, fill_ctab=True)
    return labels


def write_orig_mgz(path: Path, cras: tuple[float, float, float] = DEFAULT_CRAS) -> None:
    """8^3 conformed (LIA) volume whose centre maps to `cras` in scanner RAS."""
    rotation = np.array([[-1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])
    affine = np.eye(4)
    affine[:3, :3] = rotation
    affine[:3, 3] = np.array(cras) - rotation @ np.array([4.0, 4.0, 4.0])
    data = np.arange(512, dtype=np.uint8).reshape(8, 8, 8)
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.MGHImage(data, affine), str(path))


def write_freesurfer_subject(
    subject_dir: Path,
    *,
    cras: tuple[float, float, float] = DEFAULT_CRAS,
    atlases: tuple[str, ...] = ("aparc",),
    orig: bool = True,
    kinds: tuple[str, ...] = SURFACE_KINDS,
) -> Path:
    for hemi in ("lh", "rh"):
        for kind in kinds:
            vertices, faces = surface_vertices(hemi, kind)
            write_surface(subject_dir / "surf" / f"{hemi}.{kind}", vertices, faces, cras)
        count = surface_vertices(hemi, "pial")[0].shape[0]
        for atlas in atlases:
            write_annot(subject_dir / "label" / f"{hemi}.{atlas}.annot", count)
    if orig:
        write_orig_mgz(subject_dir / "mri" / "orig.mgz", cras)
    return subject_dir


def t1_image(
    shape: tuple[int, ...] = (24, 28, 20),
    voxel_mm: tuple[float, float, float] = (1.0, 1.0, 1.0),
    *,
    constant: bool = False,
) -> nib.Nifti1Image:
    rng = np.random.default_rng(7)
    data = np.zeros(shape, dtype=np.int16) if constant else rng.integers(0, 1000, size=shape, dtype=np.int16)
    affine = np.diag([*voxel_mm, 1.0])
    affine[:3, 3] = [-shape[0] / 2 * voxel_mm[0], -shape[1] / 2 * voxel_mm[1], -shape[2] / 2 * voxel_mm[2]]
    image = nib.Nifti1Image(data, affine)
    image.set_qform(affine, code=1)
    image.set_sform(affine, code=1)
    image.header.set_xyzt_units("mm", "sec")
    return image


def write_t1(path: Path, **kwargs: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(t1_image(**kwargs), str(path))  # type: ignore[arg-type]
    return path


def nifti_gz_bytes(**kwargs: object) -> bytes:
    """A gzipped NIfTI file as bytes (as stored inside IXI-T1.tar)."""
    image = t1_image(**kwargs)  # type: ignore[arg-type]
    raw = io.BytesIO()
    file_map = nib.Nifti1Image.make_file_map({"image": raw, "header": raw})
    image.to_file_map(file_map)
    return gzip.compress(raw.getvalue(), mtime=0)


def tar_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()
