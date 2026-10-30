# Anatomy: datasets, coordinate frames and the cortical viewer

**Status:** Implemented in Milestone 02A ([ADR-0010](decisions/ADR-0010-reference-anatomy-foundation.md)). Source localization is **not** implemented; see [What EEG source estimation still needs](#what-eeg-source-estimation-still-needs).

The viewer shows FreeSurfer cortical surfaces of a template (fsaverage), a public reference subject (OpenNeuro ds000248 `sub-01`) or, later, the owner's own reconstruction. It shows anatomy only. Nothing about the EEG stream is drawn on the cortex.

## Layers

```text
raw/<dataset>/<version>/            files exactly as distributed, verified against upstream checksums
  + <version>.acquisition.json      provenance: source URLs, license, tool versions, per-file sha256 + upstream checksum
derivatives/<dataset>/<version>/    locally computed results (e.g. a recon-all of the IXI T1)
        |
        |  neuro-engine anatomy prepare <subject>      (nibabel; offline; deterministic)
        v
assets/anatomy/<assetId>/           manifest.json + little-endian buffers; regenerable, immutable
        |
        |  GET /api/anatomy/v1/...  (engine, 127.0.0.1, GET only, CORS allowlist)
        v
desktop: anatomyClient (validate + sha256) -> useAnatomy -> AnatomyViewer -> CorticalSurfaceView (Three.js)
```

| Layer | Where | Leaves the engine? |
| --- | --- | --- |
| Raw MRI volume | `anatomy/volumes.py` `MriVolumeInfo` (shape, voxel size, affine, orientation, dtype) | Metadata only. Voxels are never served: faces are identifiable |
| Cortical surfaces and parcellations | `anatomy/surfaces.py` (nibabel FreeSurfer readers) | As asset buffers |
| Coordinate transforms | `anatomy/transforms.py` `CoordinateTransform` | In the manifest |
| EEG recording | `datasets/eeg.py` `EegInspection` (metadata only; MNE optional) | CLI output only |
| Source estimates | Not implemented | — |
| Visualization | `apps/desktop/src/anatomy/` | — |

Acquisition (`neuro_engine.acquisition`) never imports `datasets` or `anatomy`. The HTTP layer only reads already prepared assets; no endpoint downloads or processes anything.

## Coordinate frames and units

| Frame | Definition | Used for |
| --- | --- | --- |
| `freesurfer-surface-ras` | FreeSurfer "tkrRAS": +x right, +y anterior, +z superior, millimetres, origin at the centre of the conformed 256³ volume | All asset geometry, exactly as stored in `surf/?h.*` |
| `scanner-ras` | The scanner RAS of the subject's MRI, mm | Volumes (NIfTI/MGH affines) |
| `mni305-ras` | MNI305 RAS, mm | fsaverage only, where it equals surface RAS |

- **Surface RAS → scanner RAS** is a pure translation by FreeSurfer's `c_ras`. When `mri/orig.mgz` is present it is computed as `vox2ras · inv(vox2ras_tkr)` from that header and cross-checked against the `c_ras` stored in every surface's `volume_info`; a disagreement above 0.01 mm fails the asset (`inconsistent-transform`). Without `orig.mgz` the surface `c_ras` is used and the manifest says so in `transforms[].source`.
- **No arbitrary scaling.** Assets are not re-centred, scaled, decimated or re-oriented. Vertex order and count are preserved, so future source spaces and per-vertex values index the same vertices.
- **Precision.** FreeSurfer stores surfaces as big-endian float32; assets store the same values as little-endian float32, so asset positions equal the source values exactly. Scientific computation (BEM, source spaces, registration) still reads FreeSurfer files through nibabel or MNE, not the render asset.
- **LPS** (DICOM/ITK) is not used. A future DICOM path must convert explicitly with `diag(-1, -1, 1)`.
- **MNE** works in metres and calls surface RAS the `mri` frame; Neuromag `head` coordinates (from NAS/LPA/RPA) are a different frame. Conversions belong at the MNE boundary, in named functions.

### Renderer mapping (display only)

Three.js is y-up; RAS is z-up. `CorticalSurfaceView` rotates the scene group by −90° about x (`RAS_TO_SCENE_ROTATION`), i.e. `(x, y, z)_RAS → (x, z, −y)_scene`. Scene units are millimetres. Vertex buffers are uploaded unchanged.

FreeSurfer inflates each hemisphere around its own centre, so the two inflated surfaces overlap around x = 0 (verified on fsaverage and ds000248). For the **inflated** surface only, the viewer shifts each hemisphere along x so their medial extremes are `INFLATED_DISPLAY_GAP_MM` (8 mm) apart, and the provenance panel says so. Pial and white surfaces are drawn in place. Nothing is written back to data.

The initial camera looks at the centre of the displayed bounds from the left-anterior-superior direction at twice the largest extent; orbit, pan and zoom use drei `OrbitControls`. The framing only resets when the asset or surface kind changes.

## Asset contract (`anatomy-asset.v1`)

Canonical schema: [`packages/protocol/schemas/anatomy-asset.v1.schema.json`](../../packages/protocol/schemas/anatomy-asset.v1.schema.json). Generated TS types, Ajv + semantic validation (`parseAnatomyAsset`, `parseAnatomyCatalog`), a strict Pydantic mirror (`neuro_engine/protocol/anatomy_v1.py`) and shared fixtures (`fixtures/anatomy-v1/`) follow the same pattern as EEG protocol v2.

- `anatomy.asset` (`manifest.json`): subject reference, `anatomyKind` (`template` | `reference-subject` | `personal`), MRI acquisition facts with their source (`sidecar`, `dataset-readme`, `site-documentation`, `user-declared`), `coordinateFrame: "freesurfer-surface-ras"`, `units: "mm"`, transforms, surfaces, parcellations, provenance (pipeline, version, tools, source files with data-root-relative paths and SHA-256) and license.
- Buffers, little-endian: `<hemi>.<surface>.positions.f32` (`float32[3N]`, mm), `<hemi>.<surface>.indices.u32` (`uint32[3M]`, counter-clockwise seen from outside), `<hemi>.<atlas>.labels.i32` (`int32[N]`, −1 = unlabelled). Each buffer has a declared byte length and SHA-256.
- `assetId = <subject-slug>-<first 16 hex of sha256(identity)>`, where the identity covers the source file hashes, options and pipeline version. Preparing the same inputs twice gives the same ID and bytes; assets are staged and renamed atomically.
- The desktop client re-checks every buffer (byte length, SHA-256 via Web Crypto, finite coordinates inside the declared bounds, triangle indices in range, only declared labels or −1) before uploading it to the GPU. A mismatch is shown as an error with Retry, never rendered.

Endpoints (engine, loopback; [`api/anatomy.py`](../../services/neuro-engine/src/neuro_engine/api/anatomy.py)):

| Path | Response |
| --- | --- |
| `GET /api/anatomy/v1/catalog` | `anatomy.catalog`: valid assets (rescanned per request) and `defaultAssetId` (newest template) |
| `GET /api/anatomy/v1/assets/{assetId}/manifest.json` | The manifest (`Cache-Control: no-cache`) |
| `GET /api/anatomy/v1/assets/{assetId}/files/{name}` | A buffer listed in that manifest (`immutable`); anything else is 404 |

## Overlay contract (no producer)

`apps/desktop/src/anatomy/overlay.ts` defines `CorticalOverlay`: per-vertex values for one `assetId`, with quantity, unit, time and a required provenance:

| `provenance.kind` | Meaning | Label |
| --- | --- | --- |
| `synthetic` | Generated test values (generator, seed) | "Synthetic overlay — generated test values, not brain activity" |
| `estimate` | Model-derived source estimate from measured EEG (method, recording, pipeline version) | "Model-derived source estimate from scalp EEG — not a direct measurement" |
| `validated-estimate` | As above, for a pipeline that passed documented validation for this subject | "Validated model-derived source estimate — not a direct measurement" |

`overlayIssue` rejects overlays for another asset or with the wrong vertex count. Nothing creates overlays today. The viewer states "No activity overlay. The EEG stream is not mapped onto this anatomy; no source estimate is shown." The 16 synthetic stream channels are never mapped to vertices or regions. Atlas colouring is labelled as anatomical labels, not activity. A wire contract for estimates needs its own ADR.

## What EEG source estimation still needs

Having anatomy and EEG in the same app does not localize anything. Each step below is a separate, versioned artifact with its own validation:

1. **Coregistration**: a head↔MRI transform (`trans`) from fiducials and digitized electrode/head-shape points, fitted to the scalp surface, with a reported residual.
2. **Head model**: BEM surfaces (inner skull, outer skull, scalp) and conductivities, from the same reconstruction as the asset.
3. **Source space**: vertices tied to an `assetId` (same vertex identity) or a documented subsampling map.
4. **Forward model**: leadfield for the actual electrode positions and reference.
5. **Noise covariance** from baseline or empty-room data, plus preprocessing (filtering, artifact handling, bad channels).
6. **Inverse operator**: method (MNE, dSPM, sLORETA, beamformer…), regularization, depth weighting, orientation constraints.
7. **Validation**: simulations with known sources, and comparison with expected responses (e.g. ds000248 auditory/visual evoked responses).

16 consumer-grade channels give very limited spatial resolution; any future estimate must say so.

## Verified real-data facts (2026-10-30)

| Subject | Vertices (lh / rh) | Notes |
| --- | --- | --- |
| fsaverage | 163 842 / 163 842 (327 680 triangles each) | Surface RAS = MNI305; asset 36 MB with pial, white, inflated, aparc, aparc.a2009s |
| ds000248 `sub-01` | 158 443 / 161 391 | 1.5 T Siemens Sonata MPRAGE (README; the T1w sidecar has no field strength). `c_ras` ≈ (−5.27, 9.04, −27.29) mm, agrees with `orig.mgz`. T1w grid matches `rawavg.mgz`. FIF: 60 EEG channels at 600.615 Hz, 61 digitized EEG points, LPA/NASION/RPA, 78 head-shape points, bad channel `EEG 053`. Asset 37 MB (adds aparc.DKTatlas) |
| IXI012-HH-1211 | — | Philips Intera 3 T (site documentation). 256×256×150, 0.9375×0.9375×1.2 mm, int16, oblique. Not reconstructed |

Every real surface has positive signed volume (outward triangle orientation). Pial volumes are about 500–557 cm³ and white about 304–326 cm³ per hemisphere. The ds000248 `participants.tsv` starts with a UTF-8 byte-order mark; it is read with `utf-8-sig`.
