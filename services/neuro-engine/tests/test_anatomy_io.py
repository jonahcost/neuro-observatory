from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from anatomy_fixtures import (
    ANNOT_NAMES,
    DEFAULT_CRAS,
    surface_vertices,
    write_annot,
    write_orig_mgz,
    write_surface,
    write_t1,
)

from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.anatomy.surfaces import (
    read_parcellation,
    read_surface,
    signed_volume_mm3,
)
from neuro_engine.anatomy.transforms import (
    CoordinateTransform,
    fsaverage_surface_to_mni305,
    m_to_mm,
    mm_to_m,
    surface_ras_to_scanner_ras,
)
from neuro_engine.anatomy.volumes import check_mri, load_volume_info, same_voxel_grid

# --- volumes ---------------------------------------------------------------------------------


def codes(check) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.code for f in check.findings}


def test_valid_nifti_t1_is_accepted_with_metadata(tmp_path: Path) -> None:
    path = write_t1(tmp_path / "t1.nii.gz", shape=(160, 200, 180))
    check = check_mri(path)
    assert check.ok
    assert check.info.shape == (160, 200, 180)
    assert check.info.voxel_size_mm == (1.0, 1.0, 1.0)
    assert check.info.orientation == "RAS"
    assert check.info.spatial_unit == "mm"
    assert not check.info.is_oblique
    assert not codes(check) & {"coarse-voxels", "small-field-of-view", "anisotropic-voxels"}


def test_mgz_volume_is_accepted(tmp_path: Path) -> None:
    write_orig_mgz(tmp_path / "orig.mgz")
    info = load_volume_info(tmp_path / "orig.mgz")
    assert info.format == "mgh"
    assert info.orientation == "LIA"


def test_coarse_anisotropic_small_volume_warns_but_is_usable(tmp_path: Path) -> None:
    check = check_mri(write_t1(tmp_path / "t1.nii", shape=(20, 20, 20), voxel_mm=(1.0, 1.0, 3.0)))
    assert check.ok
    assert {"coarse-voxels", "anisotropic-voxels", "small-field-of-view"} <= codes(check)


def test_nominal_voxel_size_with_header_noise_does_not_warn(tmp_path: Path) -> None:
    check = check_mri(write_t1(tmp_path / "t1.nii.gz", shape=(192, 192, 150), voxel_mm=(0.9375, 0.9375, 1.200004)))
    assert "coarse-voxels" not in codes(check)


def test_constant_image_is_an_error(tmp_path: Path) -> None:
    check = check_mri(write_t1(tmp_path / "flat.nii.gz", constant=True))
    assert not check.ok
    assert "constant-image" in codes(check)


@pytest.mark.parametrize("name", ["scan.dcm", "scan.IMA", "scan.img", "scan.nrrd", "scan.mnc"])
def test_unsupported_formats_are_rejected_with_guidance(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_bytes(b"\0" * 400)
    with pytest.raises(AnatomyError) as info:
        load_volume_info(tmp_path / name)
    assert info.value.code == "unsupported-format"


def test_truncated_nifti_is_rejected(tmp_path: Path) -> None:
    path = write_t1(tmp_path / "t1.nii")
    path.write_bytes(path.read_bytes()[:200])
    with pytest.raises(AnatomyError):
        check_mri(path)


def test_four_dimensional_series_is_rejected(tmp_path: Path) -> None:
    image = nib.Nifti1Image(np.ones((8, 8, 8, 3), dtype=np.int16), np.eye(4))
    nib.save(image, tmp_path / "bold.nii.gz")
    with pytest.raises(AnatomyError) as info:
        load_volume_info(tmp_path / "bold.nii.gz")
    assert info.value.code == "not-3d"


def test_singular_affine_is_rejected(tmp_path: Path) -> None:
    image = nib.Nifti1Image(np.arange(512, dtype=np.int16).reshape(8, 8, 8), np.eye(4))
    header = image.header
    header["qform_code"] = 0
    header["sform_code"] = 1
    header["srow_z"] = [0.0, 0.0, 0.0, 0.0]
    nib.save(nib.Nifti1Image(image.dataobj, None, header), tmp_path / "bad.nii.gz")
    with pytest.raises(AnatomyError) as info:
        load_volume_info(tmp_path / "bad.nii.gz")
    assert info.value.code == "invalid-affine"


def test_unknown_nifti_units_require_an_explicit_recorded_assumption(tmp_path: Path) -> None:
    path = write_t1(tmp_path / "unknown-units.nii.gz")
    image = nib.load(path)
    image.header.set_xyzt_units(None)
    nib.save(image, path)
    with pytest.raises(AnatomyError) as info:
        load_volume_info(path)
    assert info.value.code == "unknown-units"
    assert load_volume_info(path, assume_mm=True).spatial_unit == "mm-assumed"


def test_qform_sform_disagreement_uses_absolute_world_displacement(tmp_path: Path) -> None:
    path = write_t1(tmp_path / "conflict.nii.gz", shape=(8, 8, 8))
    image = nib.load(path)
    qform = np.eye(4)
    qform[:3, 3] = 1_000_000
    sform = qform.copy()
    sform[0, 3] += 5
    image.set_qform(qform, code=1)
    image.set_sform(sform, code=1)
    nib.save(image, path)
    with pytest.raises(AnatomyError) as info:
        load_volume_info(path)
    assert info.value.code == "inconsistent-affines"


@pytest.mark.parametrize(
    ("code", "frame"),
    [(1, "scanner-ras"), (2, "aligned-ras"), (3, "talairach-ras"), (4, "mni-ras")],
)
def test_nifti_xform_code_names_the_world_frame(tmp_path: Path, code: int, frame: str) -> None:
    path = write_t1(tmp_path / f"frame-{code}.nii.gz")
    image = nib.load(path)
    image.set_qform(image.affine, code=code)
    image.set_sform(image.affine, code=code)
    nib.save(image, path)
    info = load_volume_info(path)
    assert info.affine_source == "sform" and info.world_frame == frame


def test_same_voxel_grid_compares_shape_and_affine(tmp_path: Path) -> None:
    a = load_volume_info(write_t1(tmp_path / "a.nii.gz"))
    b = load_volume_info(write_t1(tmp_path / "b.nii.gz"))
    c = load_volume_info(write_t1(tmp_path / "c.nii.gz", voxel_mm=(1.0, 1.0, 1.1)))
    assert same_voxel_grid(a, b)
    assert not same_voxel_grid(a, c)


# --- surfaces --------------------------------------------------------------------------------


def test_surface_round_trip_preserves_coordinates_and_cras(tmp_path: Path) -> None:
    vertices, faces = surface_vertices("lh", "pial")
    write_surface(tmp_path / "lh.pial", vertices, faces)
    surface = read_surface(tmp_path / "lh.pial", "lh", "pial")
    assert surface.vertex_count == 42
    assert surface.triangle_count == 80
    np.testing.assert_array_equal(surface.vertices, vertices)
    np.testing.assert_allclose(surface.cras, DEFAULT_CRAS)
    lo, hi = surface.bounds()
    assert lo[0] == pytest.approx(-65.0, abs=1e-4) and hi[0] == pytest.approx(-5.0, abs=1e-4)
    assert signed_volume_mm3(surface) > 0  # outward winding


def test_surface_without_volume_info_has_no_cras(tmp_path: Path) -> None:
    vertices, faces = surface_vertices("rh", "white")
    write_surface(tmp_path / "rh.white", vertices, faces, cras=None)
    assert read_surface(tmp_path / "rh.white", "rh", "white").cras is None


def test_missing_and_corrupt_surfaces_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(AnatomyError) as missing:
        read_surface(tmp_path / "lh.pial", "lh", "pial")
    assert missing.value.code == "missing-file"
    (tmp_path / "lh.white").write_bytes(b"not a surface")
    with pytest.raises(AnatomyError) as corrupt:
        read_surface(tmp_path / "lh.white", "lh", "white")
    assert corrupt.value.code == "unreadable-surface"


def test_degenerate_triangle_is_rejected(tmp_path: Path) -> None:
    vertices, faces = surface_vertices("lh", "pial")
    faces = faces.copy()
    faces[3] = [faces[3][0], faces[3][0], faces[3][2]]
    write_surface(tmp_path / "lh.pial", vertices, faces)
    with pytest.raises(AnatomyError) as info:
        read_surface(tmp_path / "lh.pial", "lh", "pial")
    assert info.value.code == "invalid-surface"


def test_reversed_face_is_rejected_even_when_aggregate_volume_is_positive(tmp_path: Path) -> None:
    vertices, faces = surface_vertices("lh", "pial")
    faces = faces.copy()
    faces[0] = faces[0][::-1]
    write_surface(tmp_path / "lh.pial", vertices, faces)
    with pytest.raises(AnatomyError) as info:
        read_surface(tmp_path / "lh.pial", "lh", "pial")
    assert info.value.code == "invalid-surface"


def test_open_and_zero_area_surfaces_are_rejected(tmp_path: Path) -> None:
    vertices, faces = surface_vertices("lh", "pial")
    write_surface(tmp_path / "open.pial", vertices, faces[:-1])
    with pytest.raises(AnatomyError) as opened:
        read_surface(tmp_path / "open.pial", "lh", "pial")
    assert opened.value.code == "invalid-surface"

    collinear_vertices = vertices.copy()
    a, _, c = faces[0]
    collinear_vertices[c] = collinear_vertices[a]
    write_surface(tmp_path / "flat.pial", collinear_vertices, faces)
    with pytest.raises(AnatomyError) as flat:
        read_surface(tmp_path / "flat.pial", "lh", "pial")
    assert flat.value.code == "invalid-surface"


def test_parcellation_labels_colours_and_unlabelled_vertices(tmp_path: Path) -> None:
    expected = write_annot(tmp_path / "lh.aparc.annot", 42)
    parcellation = read_parcellation(tmp_path / "lh.aparc.annot", "aparc", "lh", 42)
    np.testing.assert_array_equal(parcellation.vertex_labels, expected)
    assert parcellation.vertex_labels[0] == -1
    assert [label.name for label in parcellation.labels] == ANNOT_NAMES
    assert parcellation.labels[1].rgba == (60, 20, 220, 255)


def test_parcellation_vertex_count_must_match_surface(tmp_path: Path) -> None:
    write_annot(tmp_path / "lh.aparc.annot", 42)
    with pytest.raises(AnatomyError) as info:
        read_parcellation(tmp_path / "lh.aparc.annot", "aparc", "lh", 162)
    assert info.value.code == "invalid-annotation"


# --- transforms ------------------------------------------------------------------------------


def test_cras_only_gives_a_pure_translation() -> None:
    transform = surface_ras_to_scanner_ras(DEFAULT_CRAS)
    assert transform is not None
    np.testing.assert_allclose(transform.apply([[0, 0, 0]]), [DEFAULT_CRAS])
    assert transform.row_major()[12:] == [0.0, 0.0, 0.0, 1.0]


def test_orig_mgz_transform_agrees_with_cras(tmp_path: Path) -> None:
    write_orig_mgz(tmp_path / "orig.mgz")
    transform = surface_ras_to_scanner_ras(DEFAULT_CRAS, tmp_path / "orig.mgz")
    assert transform is not None and "orig.mgz" in transform.source
    np.testing.assert_allclose(transform.apply([[10, 20, 30]]), [[11.5, 2.75, 48.0]], atol=1e-6)


def test_disagreeing_cras_and_orig_mgz_is_an_error(tmp_path: Path) -> None:
    write_orig_mgz(tmp_path / "orig.mgz", cras=(0.0, 0.0, 0.0))
    with pytest.raises(AnatomyError) as info:
        surface_ras_to_scanner_ras(DEFAULT_CRAS, tmp_path / "orig.mgz")
    assert info.value.code == "inconsistent-transform"


def test_no_transform_without_cras_or_orig() -> None:
    assert surface_ras_to_scanner_ras(None) is None


def test_transform_validation_and_units() -> None:
    with pytest.raises(AnatomyError):
        CoordinateTransform("freesurfer-surface-ras", "scanner-ras", np.ones((4, 4)), "bad")
    with pytest.raises(AnatomyError):
        CoordinateTransform("freesurfer-surface-ras", "scanner-ras", np.full((4, 4), np.nan), "bad")
    assert fsaverage_surface_to_mni305().to_frame == "mni305-ras"
    np.testing.assert_allclose(m_to_mm([0.07]), [70.0])
    np.testing.assert_allclose(mm_to_m([70.0]), [0.07])
