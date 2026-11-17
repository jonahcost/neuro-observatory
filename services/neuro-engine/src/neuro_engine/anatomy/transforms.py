"""Coordinate frames and transforms. All anatomy geometry is in millimetres.

Frames (see docs/architecture/ANATOMY.md):
- ``freesurfer-surface-ras``: FreeSurfer "tkrRAS" surface coordinates, +x right,
  +y anterior, +z superior. MNE calls this frame ``mri`` (and uses metres).
- ``scanner-ras``: world RAS of the volume (NIfTI/MGH affine).
- ``mni305-ras``: MNI305; equal to surface RAS for fsaverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import nibabel as nib
import numpy as np
from numpy.typing import ArrayLike, NDArray

from neuro_engine.anatomy.errors import AnatomyError

CoordinateFrame = Literal["freesurfer-surface-ras", "scanner-ras", "mni305-ras"]

# FreeSurfer's c_ras and the orig.mgz header must agree to within this (mm).
CRAS_AGREEMENT_TOLERANCE_MM = 0.01


@dataclass(frozen=True, slots=True)
class CoordinateTransform:
    from_frame: CoordinateFrame
    to_frame: CoordinateFrame
    matrix: NDArray[np.float64]
    source: str

    def __post_init__(self) -> None:
        matrix = np.asarray(self.matrix, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
            raise AnatomyError("invalid-transform", "transform must be a finite 4x4 matrix")
        if not np.array_equal(matrix[3], [0.0, 0.0, 0.0, 1.0]):
            raise AnatomyError("invalid-transform", "transform last row must be [0, 0, 0, 1]")
        object.__setattr__(self, "matrix", matrix)

    def apply(self, points_mm: ArrayLike) -> NDArray[np.float64]:
        points = np.asarray(points_mm, dtype=np.float64).reshape(-1, 3)
        return points @ self.matrix[:3, :3].T + self.matrix[:3, 3]

    def row_major(self) -> list[float]:
        return [float(v) for v in self.matrix.reshape(-1)]


def m_to_mm(values: ArrayLike) -> NDArray[np.float64]:
    """MNE (metres) to anatomy (millimetres)."""
    return np.asarray(values, dtype=np.float64) * 1000.0


def mm_to_m(values: ArrayLike) -> NDArray[np.float64]:
    """Anatomy (millimetres) to MNE (metres)."""
    return np.asarray(values, dtype=np.float64) / 1000.0


def translation(offset_mm: ArrayLike) -> NDArray[np.float64]:
    matrix = np.eye(4)
    matrix[:3, 3] = np.asarray(offset_mm, dtype=np.float64).reshape(3)
    return matrix


def surface_ras_to_scanner_ras(
    cras: ArrayLike | None, orig_mgz: Path | None = None
) -> CoordinateTransform | None:
    """Surface RAS -> scanner RAS for a FreeSurfer subject.

    FreeSurfer surfaces are expressed relative to the conformed volume centre
    (`c_ras`, stored in the surface's volume_info). When ``orig.mgz`` is
    available the full transform ``vox2ras @ inv(vox2ras_tkr)`` is used and its
    translation is cross-checked against ``cras``.
    """
    if orig_mgz is not None and orig_mgz.is_file():
        try:
            header = nib.load(orig_mgz).header
            matrix = header.get_vox2ras() @ np.linalg.inv(header.get_vox2ras_tkr())
        except Exception as exc:  # nibabel raises several unrelated types for corrupt files
            raise AnatomyError("unreadable-volume", f"{orig_mgz.name}: cannot read MGH header ({type(exc).__name__})") from exc
        if cras is not None:
            difference = np.abs(matrix[:3, 3] - np.asarray(cras, dtype=np.float64))
            if float(difference.max()) > CRAS_AGREEMENT_TOLERANCE_MM:
                raise AnatomyError(
                    "inconsistent-transform",
                    f"surface c_ras and {orig_mgz.name} disagree by {float(difference.max()):.3f} mm",
                )
        matrix[3] = [0.0, 0.0, 0.0, 1.0]
        return CoordinateTransform("freesurfer-surface-ras", "scanner-ras", matrix, f"{orig_mgz.name} vox2ras * inv(vox2ras_tkr)")
    if cras is None:
        return None
    return CoordinateTransform("freesurfer-surface-ras", "scanner-ras", translation(cras), "surface volume_info c_ras")


def fsaverage_surface_to_mni305() -> CoordinateTransform:
    return CoordinateTransform("freesurfer-surface-ras", "mni305-ras", np.eye(4), "fsaverage definition (surface RAS is MNI305)")
