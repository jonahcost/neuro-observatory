# MRI reconstruction (documented, not automated)

**Status:** Documentation only ([ADR-0010](../../docs/architecture/decisions/ADR-0010-reference-anatomy-foundation.md), decision 8). Nothing in this repository runs FreeSurfer or FastSurfer, and no reconstruction of the IXI T1 or a personal MRI has been performed or validated. Do not describe a subject as reconstructed until the steps below were actually run and checked.

The cortical viewer needs a FreeSurfer subject directory (`surf/{lh,rh}.{pial,white,inflated}`, ideally `mri/orig.mgz` and `label/*.annot`). fsaverage and ds000248 `sub-01` ship one. The IXI T1 and your own MRI need a reconstruction you run yourself.

## 1. Check the input

```bash
cd services/neuro-engine
uv run neuro-engine datasets subjects                                  # find the T1 (e.g. ixi/IXI012-HH-1211)
uv run neuro-engine anatomy check-mri "<data root>/raw/ixi/ixi-t1-tar-2014-10-07/IXI012-HH-1211-T1.nii.gz"
```

`check-mri` confirms one 3D volume, a finite invertible affine and positive voxel sizes, and warns about anisotropy or voxels larger than 1.2 mm. It does not resample. For IXI012-HH-1211 it reports 256×256×150 voxels of 0.9375×0.9375×1.2 mm, oblique.

## 2. Reconstruct (outside the engine)

Requirements: a FreeSurfer installation and its free `license.txt`, or FastSurfer (Docker/Singularity, also needs the FreeSurfer license for the surface stage). Runtime is hours per subject on a CPU. Results depend on software version; record it.

FreeSurfer `recon-all`, writing straight into the location the engine discovers for IXI:

```bash
export SUBJECTS_DIR="<data root>/derivatives/ixi/ixi-t1-tar-2014-10-07/freesurfer"
mkdir -p "$SUBJECTS_DIR"
recon-all -s IXI012-HH-1211 -i "<data root>/raw/ixi/ixi-t1-tar-2014-10-07/IXI012-HH-1211-T1.nii.gz" -all
```

FastSurfer alternative (see the FastSurfer documentation for current image tags and flags):

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "<data root>/raw/ixi/ixi-t1-tar-2014-10-07:/input:ro" \
  -v "<data root>/derivatives/ixi/ixi-t1-tar-2014-10-07/freesurfer:/output" \
  -v "<path to>/license.txt:/fs_license.txt:ro" \
  deepmi/fastsurfer:<pinned version> \
  --t1 /input/IXI012-HH-1211-T1.nii.gz --sid IXI012-HH-1211 --sd /output --fs_license /fs_license.txt
```

FastSurfer produces `aparc.DKTatlas` labels rather than the Desikan `aparc`; `anatomy prepare` uses whichever atlases are present.

Never run reconstructions inside the repository, and never commit their outputs.

## 3. Validate before use

1. The run finished without errors (`scripts/recon-all.log` ends with "finished without error", or the FastSurfer log reports success).
2. Visual QC of the pial and white surfaces over the T1 (e.g. `freeview`), checking for skull-strip and topology errors.
3. `uv run neuro-engine datasets check-subject ixi/IXI012-HH-1211`: the surfaces are found, and `rawavg.mgz` matches the imported T1 voxel grid.
4. Register the reconstruction provenance (`datasets register-reconstruction`) with the input/output hashes, tool/version, privacy-safe command summary and `--qc-status passed`.
5. `uv run neuro-engine anatomy prepare ixi/IXI012-HH-1211`: geometry, `c_ras`, source hashes, QC status and `orig.mgz` consistency are checked during preparation; then `anatomy verify <assetId>`.

Record the software, version, command, runtime and QC result in the work record of the chunk that runs it.

## Personal MRI

Use a pseudonymous label and keep everything in the data root:

```bash
uv run neuro-engine datasets import-mri <T1.nii.gz> --label me --field-strength 3 --sequence MPRAGE --scanner "<model>"
# reconstruct as above, with any SUBJECTS_DIR outside the repository
uv run neuro-engine datasets import-freesurfer "$SUBJECTS_DIR/<subject>" --label me \
  --tool FreeSurfer --tool-version "<version>" \
  --command-summary "recon-all -all (privacy-safe options)" --qc-status passed
uv run neuro-engine anatomy prepare local/me
```

`import-freesurfer` requires the matching MRI to be imported first. It copies the surfaces, annotations, `orig.mgz`/`T1.mgz`/`rawavg.mgz` and the build stamp into `raw/local/1/freesurfer/me/`; it never overwrites or records the source path. It writes a versioned reconstruction record and preparation remains blocked unless acquisition hashes still match and QC is `passed`. MRI-derived meshes of a person are restricted data: they are served only on loopback and must not be committed, uploaded or shared.

DICOM input must first be converted to NIfTI (e.g. with `dcm2niix`); a DICOM path is not implemented here.
