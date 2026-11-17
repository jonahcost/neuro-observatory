"""Structural MRI volumes (NIfTI-1/2, MGH/MGZ) read with nibabel.

Only header metadata leaves this module. Voxel data stays in the engine
process; it is read solely to verify integrity (gzip CRC, finite values).
"""

from __future__ import annotations

import gzip
import math
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import nibabel as nib
import numpy as np
from nibabel.filebasedimages import ImageFileError
from numpy.typing import NDArray

from neuro_engine.anatomy.errors import AnatomyError

VolumeFormat = Literal["nifti1", "nifti2", "mgh"]
AffineSource = Literal["qform", "sform", "mgh"]

_SUPPORTED_SUFFIXES = {".nii": "nifti", ".nii.gz": "nifti", ".mgz": "mgh", ".mgh": "mgh"}
_REJECTED_SUFFIXES = {
    ".dcm": "DICOM is not supported; convert the series to NIfTI first (for example with dcm2niix)",
    ".ima": "Siemens IMA/DICOM is not supported; convert the series to NIfTI first (for example with dcm2niix)",
    ".img": "Analyze 7.5 .img/.hdr pairs are not supported; convert to NIfTI",
    ".hdr": "Analyze 7.5 .img/.hdr pairs are not supported; convert to NIfTI",
    ".nrrd": "NRRD is not supported; convert to NIfTI",
    ".mnc": "MINC is not supported; convert to NIfTI",
}
# NIfTI xyzt_units spatial codes.
_NIFTI_SPATIAL_UNITS = {"unknown", "mm", "meter", "micron"}
# FreeSurfer's recon-all is designed for ~1 mm isotropic T1 volumes.
MAX_RECOMMENDED_VOXEL_MM = 1.2
MAX_RECOMMENDED_ANISOTROPY = 1.5
MIN_RECOMMENDED_FOV_MM = 150.0
# Header voxel sizes carry float noise (e.g. a nominal 1.2 mm slice stored as 1.200004).
VOXEL_SIZE_TOLERANCE_MM = 0.01
MAX_VOXELS = 200_000_000
MAX_DECODED_BYTES = 2_000_000_000
AFFINE_AGREEMENT_ATOL_MM = 1e-3
_XFORM_FRAMES = {
    0: "unknown-world-ras",
    1: "scanner-ras",
    2: "aligned-ras",
    3: "talairach-ras",
    4: "mni-ras",
}


def volume_suffix(path: Path) -> str:
    name = path.name.lower()
    return ".nii.gz" if name.endswith(".nii.gz") else path.suffix.lower()


@dataclass(frozen=True, slots=True)
class MriVolumeInfo:
    """Header facts for one volume. `affine` maps voxel indices to the declared world RAS frame in mm."""

    file_name: str
    format: VolumeFormat
    shape: tuple[int, ...]
    voxel_size_mm: tuple[float, float, float]
    affine: NDArray[np.float64]
    orientation: str
    qform_code: int | None
    sform_code: int | None
    dtype: str
    spatial_unit: str
    affine_source: AffineSource
    world_frame: str

    @property
    def field_of_view_mm(self) -> tuple[float, float, float]:
        return tuple(float(n * s) for n, s in zip(self.shape[:3], self.voxel_size_mm, strict=True))  # type: ignore[return-value]

    @property
    def is_oblique(self) -> bool:
        rotation = self.affine[:3, :3] / np.asarray(self.voxel_size_mm)
        return not np.allclose(np.abs(rotation), np.round(np.abs(rotation)), atol=1e-3)

    def summary(self) -> dict[str, object]:
        return {
            "fileName": self.file_name,
            "format": self.format,
            "shape": list(self.shape),
            "voxelSizeMm": [round(v, 6) for v in self.voxel_size_mm],
            "fieldOfViewMm": [round(v, 3) for v in self.field_of_view_mm],
            "orientation": self.orientation,
            "oblique": self.is_oblique,
            "qformCode": self.qform_code,
            "sformCode": self.sform_code,
            "dtype": self.dtype,
            "spatialUnit": self.spatial_unit,
            "affineSource": self.affine_source,
            "worldFrame": self.world_frame,
            "voxelToWorldRasMm": [[round(float(v), 6) for v in row] for row in self.affine],
        }


@dataclass(frozen=True, slots=True)
class Finding:
    level: Literal["error", "warning", "info"]
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MriCheck:
    info: MriVolumeInfo
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.findings)


def load_volume_info(path: Path, *, assume_mm: bool = False) -> MriVolumeInfo:
    """Read and validate a volume header. Raises AnatomyError."""
    suffix = volume_suffix(path)
    if suffix in _REJECTED_SUFFIXES:
        raise AnatomyError("unsupported-format", f"{path.name}: {_REJECTED_SUFFIXES[suffix]}")
    if suffix not in _SUPPORTED_SUFFIXES:
        raise AnatomyError(
            "unsupported-format", f"{path.name}: expected .nii, .nii.gz, .mgz or .mgh (got '{suffix or 'no suffix'}')"
        )
    if not path.is_file():
        raise AnatomyError("missing-file", f"{path.name} not found")
    try:
        image = nib.load(path)
    except (ImageFileError, OSError, EOFError, ValueError, zlib.error, gzip.BadGzipFile) as exc:
        raise AnatomyError("unreadable-volume", f"{path.name}: cannot read header ({type(exc).__name__})") from None

    if isinstance(image, nib.Nifti2Image):
        fmt: VolumeFormat = "nifti2"
    elif isinstance(image, nib.Nifti1Image):
        fmt = "nifti1"
    elif isinstance(image, nib.MGHImage):
        fmt = "mgh"
    else:
        raise AnatomyError("unsupported-format", f"{path.name}: {type(image).__name__} is not a supported volume type")

    shape = tuple(int(n) for n in image.shape)
    if len(shape) == 4 and shape[3] == 1:
        shape = shape[:3]
    if len(shape) != 3:
        raise AnatomyError("not-3d", f"{path.name}: expected one 3D volume, got shape {shape}")
    if min(shape) < 2:
        raise AnatomyError("invalid-volume", f"{path.name}: degenerate shape {shape}")
    voxel_count = math.prod(shape)
    decoded_bytes = voxel_count * max(8, int(image.header.get_data_dtype().itemsize))
    if voxel_count > MAX_VOXELS or decoded_bytes > MAX_DECODED_BYTES:
        raise AnatomyError(
            "volume-too-large",
            f"{path.name}: {voxel_count} voxels / up to {decoded_bytes} decoded bytes exceeds the safety limit",
        )

    affine_source: AffineSource = "mgh"
    world_frame = "scanner-ras"
    affine = np.asarray(image.affine, dtype=np.float64)
    if affine.shape != (4, 4) or not np.all(np.isfinite(affine)):
        raise AnatomyError("invalid-affine", f"{path.name}: affine is not a finite 4x4 matrix")
    if abs(float(np.linalg.det(affine[:3, :3]))) < 1e-9:
        raise AnatomyError("invalid-affine", f"{path.name}: affine is singular")
    zooms = tuple(float(z) for z in image.header.get_zooms()[:3])
    if len(zooms) != 3 or not all(np.isfinite(z) and z > 0 for z in zooms):
        raise AnatomyError("invalid-voxel-size", f"{path.name}: voxel sizes must be positive and finite")

    qform_code: int | None = None
    sform_code: int | None = None
    spatial_unit = "mm"
    if fmt in ("nifti1", "nifti2"):
        header = image.header
        qform_code = int(header["qform_code"])
        sform_code = int(header["sform_code"])
        qform = np.asarray(image.get_qform(), dtype=np.float64) if qform_code > 0 else None
        sform = np.asarray(image.get_sform(), dtype=np.float64) if sform_code > 0 else None
        if qform is not None and sform is not None:
            corners = np.array(
                [
                    [i, j, k, 1.0]
                    for i in (0, shape[0] - 1)
                    for j in (0, shape[1] - 1)
                    for k in (0, shape[2] - 1)
                ],
                dtype=np.float64,
            )
            q_world = corners @ qform.T
            s_world = corners @ sform.T
            difference = float(np.linalg.norm(q_world[:, :3] - s_world[:, :3], axis=1).max())
            if difference > AFFINE_AGREEMENT_ATOL_MM:
                raise AnatomyError(
                    "inconsistent-affines",
                    f"{path.name}: qform and sform disagree by up to {difference:.3f} mm across the volume",
                )
        if sform is not None:
            affine = sform
            affine_source = "sform"
            world_frame = _XFORM_FRAMES.get(sform_code, "unknown-world-ras")
        elif qform is not None:
            affine = qform
            affine_source = "qform"
            world_frame = _XFORM_FRAMES.get(qform_code, "unknown-world-ras")
        else:
            raise AnatomyError("no-affine", f"{path.name}: qform_code and sform_code are both 0")
        spatial_unit = str(header.get_xyzt_units()[0])
        if spatial_unit not in _NIFTI_SPATIAL_UNITS:
            spatial_unit = "unknown"
        if spatial_unit in ("meter", "micron"):
            raise AnatomyError(
                "unsupported-units", f"{path.name}: spatial units are '{spatial_unit}'; anatomy requires millimetres"
            )
        if spatial_unit == "unknown":
            if not assume_mm:
                raise AnatomyError(
                    "unknown-units",
                    f"{path.name}: spatial units are unset; use an explicit millimetre assumption only when source documentation supports it",
                )
            spatial_unit = "mm-assumed"

    return MriVolumeInfo(
        file_name=path.name,
        format=fmt,
        shape=shape,
        voxel_size_mm=zooms,  # type: ignore[arg-type]
        affine=affine,
        orientation="".join(nib.aff2axcodes(affine)),
        qform_code=qform_code,
        sform_code=sform_code,
        dtype=str(image.get_data_dtype()),
        spatial_unit=spatial_unit,
        affine_source=affine_source,
        world_frame=world_frame,
    )


def read_voxels_checked(path: Path) -> NDArray[np.floating]:
    """Read voxel data (verifies gzip CRC and finiteness). Never logged or exported."""
    try:
        data = np.asanyarray(nib.load(path).dataobj)
    except (OSError, EOFError, ValueError, zlib.error, gzip.BadGzipFile) as exc:
        raise AnatomyError("corrupt-volume", f"{path.name}: voxel data is unreadable ({type(exc).__name__})") from None
    if np.issubdtype(data.dtype, np.floating) and not np.all(np.isfinite(data)):
        raise AnatomyError("corrupt-volume", f"{path.name}: voxel data contains non-finite values")
    return data


def check_mri(path: Path, *, read_data: bool = True, assume_mm: bool = False) -> MriCheck:
    """Validate a T1-weighted volume as FreeSurfer input. Does not resample or modify it."""
    info = load_volume_info(path, assume_mm=assume_mm)
    findings: list[Finding] = []
    if read_data:
        data = read_voxels_checked(path)
        if float(np.max(data)) <= float(np.min(data)):
            findings.append(Finding("error", "constant-image", "all voxels have the same value"))
    largest = max(info.voxel_size_mm)
    smallest = min(info.voxel_size_mm)
    if largest > MAX_RECOMMENDED_VOXEL_MM + VOXEL_SIZE_TOLERANCE_MM:
        findings.append(
            Finding(
                "warning",
                "coarse-voxels",
                f"largest voxel dimension {largest:.3f} mm exceeds {MAX_RECOMMENDED_VOXEL_MM} mm; "
                "recon-all expects about 1 mm isotropic T1 data",
            )
        )
    if largest / smallest > MAX_RECOMMENDED_ANISOTROPY:
        findings.append(
            Finding("warning", "anisotropic-voxels", f"voxel anisotropy {largest / smallest:.2f} exceeds {MAX_RECOMMENDED_ANISOTROPY}")
        )
    if min(info.field_of_view_mm) < MIN_RECOMMENDED_FOV_MM:
        findings.append(
            Finding(
                "warning",
                "small-field-of-view",
                f"smallest field of view {min(info.field_of_view_mm):.1f} mm may not cover the whole head",
            )
        )
    if info.is_oblique:
        findings.append(Finding("info", "oblique", "voxel axes are oblique to scanner axes; recon-all handles this"))
    if info.spatial_unit == "mm-assumed":
        findings.append(Finding("warning", "assumed-mm", "spatial units were unset; millimetres were explicitly assumed"))
    findings.append(Finding("info", "orientation", f"voxel axes point to {info.orientation} (nibabel axis codes)"))
    return MriCheck(info=info, findings=tuple(findings))


def same_voxel_grid(a: MriVolumeInfo, b: MriVolumeInfo, *, atol_mm: float = 1e-3) -> bool:
    """True when both volumes share shape and voxel-to-scanner affine (e.g. a T1w and FreeSurfer's rawavg.mgz)."""
    return a.shape == b.shape and bool(np.allclose(a.affine, b.affine, atol=atol_mm))
