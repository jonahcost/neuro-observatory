# ADR-0010: Milestone 02A: Reference neuroimaging datasets and cortical anatomy viewer

- Status: Accepted
- Date: 2026-10-30
- Decision Owner: Project owner (plan approved with the recommended options 2026-10-30; accepted as implemented, including the Implementation Notes, 2026-10-30 in chat)
- Related Work: `docs/work/completed/WORK-2026-10-30-reference-anatomy-foundation.md`
- Supersedes: None (implements ADR-0005 and ADR-0006 for anatomy; extends ADR-0002 and ADR-0003)

## Context

Verified state on `main` at `5356474` (2026-10-30):

- **Desktop** (`apps/desktop/src/app/app.tsx`) renders a rotating wireframe sphere labelled "does not represent brain activity". `three` 0.186, `@react-three/fiber` 9.8 and `@react-three/drei` 10.7 are already dependencies. There is no anatomy code, scene model or HTTP client.
- **Engine** (`services/neuro-engine`) is a FastAPI app on `127.0.0.1:8000` that owns synthetic EEG acquisition (ADR-0008/0009): `/health`, `/api/v2/stream`, `/ws/v2/eeg`. Runtime dependencies are `fastapi`, `numpy`, `pydantic` and `uvicorn`. Settings use the `NEURO_ENGINE_` prefix. There is no MRI, dataset or CLI code; the `neuro-engine` console script prints "Hello".
- **Protocol** (`packages/protocol`) has only the EEG stream v2 contract (JSON Schema → generated TS + Ajv; Pydantic mirror; shared fixtures).
- `pipelines/mri-reconstruction` and `pipelines/electrode-registration` are empty placeholders.
- **Governance**: `.nii`, `.nii.gz`, `.fif`, `.dcm`, `.edf`, `.bdf`, `.xdf` and paths under `data/`, `datasets/`, `recordings/`, `models/`, `artifacts/` are rejected by `check_governance.py` and ignored by Git and Cursor. CI must not need network, MRI or hardware.
- **Toolchain on the development Mac**: no FreeSurfer (`recon-all` absent, no `FREESURFER_HOME`), no MNE, no `~/mne_data`. 1.7 TB free disk.
- ADR-0005 requires structural MRI, measured EEG and model estimates to stay separate and labelled. ADR-0006 requires a scene model independent of Three.js.

Dataset facts verified on 2026-10-30 from the official sources:

| Dataset | Source and version | License | Size | Notes |
| --- | --- | --- | --- | --- |
| fsaverage | `mne.datasets.fetch_fsaverage` (MNE 1.13.2). Two OSF archives pinned by MD5 in MNE's code: `osf.io/download/3bxqt?version=2` (`5133fe92b7b8f03ae19219d5f46e4177`, 195.9 MB) and `osf.io/download/7ve8g?version=4` (`b31509cdcf7908af6a83dc5ee8f49fb1`, 231.1 MB, BEM) | FreeSurfer Software License v1.0 (research use; redistribution must carry the license and mark modifications) | 0.43 GB download | FreeSurfer 6 template; surface RAS equals MNI305. Calls `set_config("SUBJECTS_DIR")` (writes `~/.mne`) when no subjects dir is configured |
| OpenNeuro ds000248 | Snapshot `1.2.4` (2020-12-11), DOI `10.18112/openneuro.ds000248.v1.2.4`. Per-file versioned S3 URLs from the OpenNeuro GraphQL API | CC0; authors ask for MNE citations | 2.07 GB, 1 229 files (OpenNeuro's summary "186 MB" excludes derivatives) | `sub-01`: `anat/sub-01_T1w.nii.gz` (+ FLASH), `meg/sub-01_task-audiovisual_run-01_meg.fif` (306 MEG + **60 EEG** channels, 600.615 Hz, 60 Hz line), `derivatives/freesurfer/subjects/{sub-01,fsaverage}`. T1w sidecar has `AnatomicalLandmarkCoordinates` (NAS/LPA/RPA, voxels) but **no field-strength fields**; the README states Siemens 1.5 T Sonata, MPRAGE. Annexed files carry `MD5E-s<size>--<md5>` keys; others carry git blob SHA-1 |
| IXI | `IXI-T1.tar` only (4 840 816 640 bytes, `Last-Modified` 2014-10-07). Server supports HTTP range requests | CC BY-SA 3.0 | 4.84 GB archive | Member 1 is `IXI012-HH-1211-T1.nii.gz` (offset 6 944 256, 10 120 330 bytes). HH = Hammersmith, Philips Intera 3T; T1 site parameters TR 9.6 ms, TE 4.6 ms, flip 8°, 208×208 matrix, 240 mm FOV. NIfTI headers carry no scanner metadata. `IXI.xls` contains demographics (date of birth, ethnicity) |

`openneuro-py` (the OpenNeuro CLI) is GPL-3.0-only; this repository is MIT.

## Decision

Accepted. For items marked **(owner choice)** the owner chose the option described here; alternatives are listed below.

### 1. Where the code lives

Dataset management and anatomy preparation go in new subpackages of the existing engine: `neuro_engine.datasets` and `neuro_engine.anatomy`, plus a stdlib `argparse` CLI behind the existing `neuro-engine` console script. They are offline batch code: acquisition never imports them, and nothing runs inside the acquisition event loop. The HTTP layer only reads already-prepared assets. FreeSurfer `recon-all` stays an external tool documented under `pipelines/mri-reconstruction/` (decision 8).

### 2. Storage **(owner choice)**

One configurable root, `NEURO_ENGINE_DATA_DIR`. The default is a per-user directory outside the repository: `~/Library/Application Support/NeuroObservatory` on macOS, `$XDG_DATA_HOME/neuro-observatory` (or `~/.local/share/neuro-observatory`) elsewhere.

```text
<root>/raw/<dataset>/<version>/                 source files exactly as distributed; never modified after verification
<root>/raw/<dataset>/<version>.acquisition.json provenance record (decision 4)
<root>/downloads/                               partial downloads (*.part); resumable; safe to delete
<root>/derivatives/<dataset>/<version>/<subject>/  locally computed derivatives (future recon-all, coregistration)
<root>/assets/anatomy/<assetId>/                app-ready geometry; fully regenerable from raw/ + derivatives/
```

The CLI refuses a root inside a Git working tree unless the path is Git-ignored. Logs name dataset IDs and relative paths, never the absolute root (which contains the user name).

### 3. Datasets and acquisition **(owner choice for ds000248 tooling and IXI)**

A code-defined catalog (`DatasetSpec`: ID, title, pinned version, source URLs, license and attribution, expected sizes, modalities, acquisition notes) for `fsaverage`, `ds000248` and `ixi`, plus `local` for user imports.

- **fsaverage** (default anatomy): `mne.datasets.fetch_fsaverage(subjects_dir=<root>/raw/fsaverage/<version>)`, with `SUBJECTS_DIR` set in-process only so MNE does not write `~/.mne`. MNE verifies the archive hashes; afterwards we hash the files we use.
- **ds000248 `1.2.4`**: a small stdlib downloader on the OpenNeuro GraphQL API. It lists the snapshot tree, downloads the snapshot's versioned S3 URLs, resumes with HTTP `Range` into `*.part`, and verifies every file: size plus MD5 from git-annex keys, or size plus git blob SHA-1 for small non-annexed files. Profiles: `anatomy` (default, 30 files, 194 MB: top-level metadata, all of `sub-01/`, FreeSurfer `sub-01` pial/white/inflated surfaces, `aparc`/`aparc.a2009s`/`aparc.DKTatlas` annotations, `T1.mgz`/`orig.mgz`/`rawavg.mgz`, BEM surfaces) and `full` (2.07 GB, needs `--confirm-large`). We do not use the separately distributed MNE "sample" archive. Its content overlaps, but it is a different release with different file names.
- **IXI**: `import` of a locally obtained `IXI*-T1.nii.gz` (always supported). Optionally, `fetch ixi --subject IXI012-HH-1211` reads the 512-byte tar header with one range request and downloads only that member's byte range (10.1 MB). Integrity comes from the tar header checksum, the size and the gzip CRC-32 on decompression. IXI publishes no checksums, so we record the SHA-256 we observe. `IXI.xls` is never downloaded or imported.
- **local**: `import-mri` (NIfTI T1 → `raw/local/...`) and `import-freesurfer` (an existing FreeSurfer subject directory) are the path for the owner's own MRI. `--anatomy-kind personal` marks the result as personal.

Downloads are idempotent: verified files are skipped. Anything larger than 500 MB, and any license acceptance, needs an explicit `--confirm-large` / `--accept-license` flag. Errors name the dataset, the file and the next action. Nothing is downloaded at engine startup, from the UI, or in CI.

### 4. Provenance and licensing

Each acquisition writes `acquisition.json`: dataset ID and version, DOI, source URLs, license ID, URL and attribution text, tool name and version (neuro-engine, MNE), UTC timestamps, and per-file relative path, size, SHA-256 and upstream checksum. Imports record the original file name (not its absolute path) and the user-declared field strength and sequence. Field strength is labelled with its source: `sidecar`, `dataset-readme`, `site-documentation` or `user-declared`. For ds000248 the 1.5 T value comes from the README. IXI's 3 T and T1 parameters come from the HH site page and are site-level, not per-scan. Asset manifests carry license and attribution, and the viewer shows them.

### 5. Anatomical data model (separate layers)

| Layer | Python type (engine) | Leaves the engine? |
| --- | --- | --- |
| Raw image | `MriVolumeInfo`: format (NIfTI-1/2, MGH/MGZ), shape, voxel size (mm), voxel→scanner-RAS affine, orientation codes, q/sform codes, dtype, SHA-256 | Metadata only; voxels never (faces are identifiable) |
| Processed geometry | `CorticalSurface` (hemisphere, kind `pial`/`white`/`inflated`, float64 vertices in mm, int32 triangles, FreeSurfer `volume_info`), `Parcellation` (atlas, per-vertex label index, label table) | Via asset files |
| Coordinate transforms | `CoordinateTransform(from_frame, to_frame, 4×4, units)` | In manifests |
| Electrophysiology | `EegRecordingInfo`: inspection summary only (channel count and types, sampling rate, digitization present, coordinate frame) | Not streamed |
| Source estimates | Not implemented (decision 9) | — |
| Visualization | Asset manifest plus binary buffers (decision 7) | Yes, over loopback |

A subject is `(datasetId, datasetVersion, subjectId, sessionId?)`. `anatomyKind` is `template` (fsaverage), `reference-subject` (ds000248, IXI) or `personal` (the owner's MRI).

### 6. Coordinate systems and units

- Geometry is in **millimetres** in **FreeSurfer surface RAS** ("tkrRAS"; +x right, +y anterior, +z superior), exactly as stored in the FreeSurfer files. Assets are not re-centred, scaled, decimated or reoriented. Vertex order and count are preserved, so future source spaces and per-vertex estimates index the same vertices.
- Volumes keep their own voxel→**scanner RAS** affine (NIfTI/MGH, mm). Surface RAS → scanner RAS is the translation from the surface's `volume_info` (`cras`), cross-checked against `orig.mgz` (`vox2ras` · `vox2ras_tkr`⁻¹) when available, and stored in the manifest. For fsaverage, surface RAS equals MNI305 RAS.
- LPS (DICOM/ITK) is not used internally. A future DICOM path converts explicitly with `diag(-1, -1, 1)`.
- MNE uses **metres** and calls FreeSurfer surface RAS the `mri` frame. Neuromag `head` coordinates (from NAS/LPA/RPA) are a separate frame. Conversion happens only at the MNE boundary, in named functions (`m_to_mm`).
- Rendering: one view transform in the renderer adapter maps RAS to Three.js (y-up) with a rotation and a uniform mm→scene-unit scale. Inflated surfaces get a lateral display offset per hemisphere, which the UI labels. None of this is written back to data.

### 7. Anatomy asset contract and serving **(owner choice for serving)**

- New canonical schema `packages/protocol/schemas/anatomy-asset.v1.schema.json` (`anatomy.catalog`, `anatomy.asset`, `schemaVersion: 1`) with generated TS types, Ajv validation plus semantic checks (`parseAnatomyAsset`), a Pydantic mirror in the engine, and shared valid/invalid fixtures run in both languages. This is the same pattern as ADR-0008 decision 1. The EEG v2 contract is unchanged.
- Binary buffers are little-endian: positions `float32[3N]` (mm, surface RAS), triangles `uint32[3M]`, parcellation labels `int32[N]` (-1 = unlabelled). The manifest declares counts, byte lengths, SHA-256, bounds, frame, units, transforms, label tables, provenance and license. `assetId` is a content hash of sources, options and pipeline version, so assets are immutable.
- float32 positions are lossless: FreeSurfer stores surfaces as float32, so asset positions equal the source values (see Implementation Notes). Scientific computation (BEM, source spaces, registration) still reads the FreeSurfer sources through nibabel or MNE, never the render asset.
- Full resolution is kept (fsaverage: 163 842 vertices and 327 680 triangles per hemisphere, about 5.9 MB per hemisphere-surface). The viewer loads one surface type at a time (about 12 MB). Decimation is deferred until it can keep a vertex map.
- The engine serves read-only `GET /api/anatomy/v1/assets`, `GET /api/anatomy/v1/assets/{assetId}/manifest`, and `GET /api/anatomy/v1/assets/{assetId}/files/{name}`. These run on the existing loopback port. Only names listed in the manifest are served, after path containment checks. Content-addressed files get immutable cache headers. CORS allows only the existing `NEURO_ENGINE_ALLOWED_ORIGINS`, GET only, no credentials. The asset directory is rescanned on each listing, so newly prepared subjects appear without a restart. Nothing is sent over the EEG WebSocket. No endpoint starts downloads or processing.

### 8. MRI processing boundary

This milestone does not run FreeSurfer: it is not installed, it needs a license file, and `recon-all` takes hours. `neuro-engine anatomy check-mri` validates a T1 for FreeSurfer input: one 3D volume, finite invertible affine, positive voxel sizes, warnings for anisotropy or voxels larger than 1.2 mm, orientation report. It does not resample. `pipelines/mri-reconstruction/README.md` documents `recon-all` (and the FastSurfer alternative), inputs, outputs, expected runtime and `import-freesurfer`. No reconstruction is claimed until it is run and validated.

### 9. EEG and anatomy integration boundary

- Target pipeline: acquisition (protocol v2) → preprocessing → electrode registration (head↔MRI transform from fiducials and digitized positions) → forward model (BEM plus source space tied to an `assetId`) → inverse operator (method, regularization, noise covariance) → source estimates → viewer overlay. Each stage is a separate versioned artifact.
- In this milestone the viewer shows anatomy only, and says so: "No activity overlay". The 16 synthetic channels are never mapped to vertices or regions. A synthetic demo overlay is **not** added. Parcellation colouring is labelled "anatomical atlas (labels, not activity)".
- The renderer gets a per-vertex colour path, used now by parcellations. A typed `CorticalOverlay` (`provenance: 'source-estimate'`, `assetId`, `vertexCount`, method, units) is defined but has no producer. The viewer rejects overlays whose `assetId` or vertex count does not match. A future source-estimate wire contract needs its own ADR.
- For ds000248 the engine reports whether the FIF has digitized EEG positions and whether the T1w sidecar has landmarks: the inputs a later registration chunk needs. It does not compute a head↔MRI transform or a forward/inverse solution here.

### 10. Dependencies

- Python runtime: **`nibabel`** (MIT; depends only on `numpy` and `packaging`) for NIfTI, MGH and FreeSurfer surface/annotation I/O. CI needs it.
- Python optional extra `neuroimaging`: **`mne`** (BSD-3; pulls `scipy`, `matplotlib`, `pooch`, `tqdm`, `jinja2`) and **`mne-bids`** (BSD-3), for fetching fsaverage and inspecting BIDS/FIF. CI does not install them; tests that need them skip.
- No `openneuro-py`, DataLad, glTF tooling or new JS dependencies.
- New Nx target `neuro-engine:test-integration` (uncached, opt-in; needs local data). CI is unchanged.

## Alternatives Considered

- **New `pipelines/anatomy` uv project** instead of engine subpackages: matches "pipelines own reconstructions". But it adds a second Python environment and Nx project, and the engine would still need the manifest model to serve assets (duplicate models or a third shared package). Proposed only for the future `recon-all` wrapper.
- **ds000248 via `openneuro-py`** (official, but GPL-3.0-only, with typer/rich/niquests dependencies). Or run it externally with `uvx` (no import, but an unpinned toolchain fetched at run time). Or **DataLad** (MIT, but needs a system git-annex install). Or **AWS CLI on the S3 bucket** (latest objects only, no snapshot pinning). Or the **MNE sample archive** (different release; the task asks for OpenNeuro).
- **glTF/GLB** instead of JSON manifest plus raw buffers: a standard format and directly loadable. But units, frame, transforms, per-vertex labels and provenance would live in custom extras, the loader can apply implicit transforms, and it adds a dependency. A GLB export can be added later.
- **Serving**: a Vite dev proxy (no CORS, but nothing in preview or a future Tauri shell), copying assets into `apps/desktop/public` (puts MRI-derived data in the repo tree), or the EEG WebSocket (forbidden by the task; wrong channel).
- **Decimating meshes now**: smaller transfers, but this breaks vertex correspondence with future source spaces.
- **MNE as a core dependency** (simpler, but about 150 MB of scientific stack in the engine and in CI for features CI cannot exercise). **nilearn** (heavier, not needed).
- **Data root inside the repo** (`./data`, ignored by Git and Cursor): easier to find, but personal MRI data would sit in a working tree that may be synced or zipped.
- **Synthetic activity demo overlay**: shows the colour path, but invites the exact misreading ADR-0005 forbids. Rejected for now.
- **Server-side rendering** (PyVista, brainrender): puts GPU code in the engine, contrary to OVERVIEW ownership.
- **Retain current state**: a placeholder sphere gives no anatomical basis for later work.

## Consequences

- Benefits: real, provenance-tracked cortical anatomy in the viewer, with the template, a real reference subject and a future personal subject going through the same path. Coordinates and vertex identity are preserved for registration and source modelling. Offline after acquisition. CI stays network-free.
- Costs: one runtime dependency (`nibabel`) and an optional heavy extra (`mne`, `mne-bids`). A second canonical schema with its Pydantic mirror, guarded by shared fixtures. New HTTP endpoints and CORS on the loopback engine. About 0.9 GB of local disk for fsaverage plus the ds000248 anatomy profile, and about 36 MB of assets per subject. Our own OpenNeuro downloader to maintain (GraphQL API changes would break it; errors say so).
- Scientific: template anatomy is not the user's brain. ds000248 is 1.5 T and IXI's parameters are site-level. float32 render geometry must not be used for computation. No registration or source localization exists after this milestone, and the UI must say so.
- Privacy and security: personal MRI-derived meshes are restricted data (`docs/standards/security.md`). They are served only on loopback to allowlisted origins and never committed. Volumes are never served. IXI demographics are not ingested. Downloads are explicit CLI actions to the documented hosts only (osf.io, openneuro.org and its S3 bucket, biomedic.doc.ic.ac.uk).
- Licensing: the FreeSurfer license terms must accompany any redistribution of fsaverage-derived assets (we do not redistribute). IXI derivatives are share-alike. ds000248 is CC0 with a citation request.

## Validation and Rollback

Validation (results go in the work record):

- CI-safe tests with synthetic fixtures generated at test time (no `.nii`/`.fif` in Git): an icosphere written with nibabel's FreeSurfer writers and synthetic NIfTI/MGH volumes. They cover parsing, vertex and triangle counts, index range, finite coordinates, bounds, hemisphere handling, units and frame metadata, the surface-RAS→scanner transform, corrupt, truncated, missing and unsupported files, catalog and provenance records, download verification (MD5, git blob SHA-1, size, resume, mismatch) against a local fake server or transport, IXI tar-header parsing, storage-root guards, asset determinism (same input gives the same `assetId` and bytes), manifest fixture parity across TS and Python, API listing, manifest and file serving (traversal, unknown asset, CORS), the desktop client's validation and abort-on-switch, and panel states (loading, empty, error, ready, labels).
- Opt-in integration tests (`neuro-engine:test-integration`) run against real local data: fsaverage geometry (163 842 vertices per hemisphere, outward triangle orientation via positive signed volume, MNI305 bounds), ds000248 `sub-01` (T1w grid matches `rawavg.mgz`, subject and BIDS entities agree, 60 EEG channels readable with MNE) and the IXI HH T1 (3D, about 1 mm voxels, valid affine).
- Existing checks: `yarn nx run-many -t lint test typecheck build`, `check-generated`, engine pytest/ruff, governance checks. Plus a manual browser check of the viewer against a live engine with prepared fsaverage.

Rollback: revert the change set as a unit. EEG protocol v2 and acquisition are untouched. Downloaded data and assets live outside the repository and can be removed with `rm -rf <root>`. No migration is needed.

## Implementation Notes (2026-10-30, accepted with the decision)

Where the implementation differs from the text above, or the real data taught us something. Evidence is in the work record.

- **Precision correction** (decision 7): the plan called float32 "render-only, about 1e-5 mm". FreeSurfer surface files are big-endian float32, so little-endian float32 assets reproduce them exactly. The bullet was corrected; the rule that computation uses the FreeSurfer sources is unchanged.
- **Endpoints** (decision 7): implemented as `GET /api/anatomy/v1/catalog`, `/assets/{assetId}/manifest.json` and `/assets/{assetId}/files/{name}`. The catalog default is the newest template asset. The desktop has a **Refresh subjects** button to pick up newly prepared assets.
- **Transform source** (decision 6): surface RAS → scanner RAS comes from `orig.mgz` (`vox2ras · inv(vox2ras_tkr)`) when present and must agree with every surface's `c_ras` within 0.01 mm; otherwise the surface `c_ras` is used. The manifest records which.
- **Personal anatomy** (decision 3): there is no `--anatomy-kind` flag. Everything imported with `import-mri` / `import-freesurfer` belongs to the `local` dataset, whose kind is `personal`, under a pseudonymous `--label`.
- **Overlay type** (decision 9): `CorticalOverlay.provenance.kind` is `synthetic`, `estimate` or `validated-estimate`, each with its own UI label, so a future synthetic test overlay cannot be shown as an estimate. There is still no producer and no synthetic overlay in the app.
- **ds000248 anatomy profile**: 36 files, 201 537 926 bytes (planned estimate: 30 files, 194 MB): top-level metadata (`README`, `CHANGES`, `dataset_description.json`, `participants.tsv/json`), all 12 files of `sub-01/`, and 19 FreeSurfer files (6 surfaces, 6 annotations, 3 volumes, 3 BEM surfaces, `scripts/build-stamp.txt`).
- **IXI**: the member's tar header is at offset 6 944 256 and its data at 6 944 768. The recorded upstream checksum is `tar-member:IXI-T1.tar@6944768+10120330;gzip-crc32-verified`.
- **Real-data findings**: ds000248 `participants.tsv` starts with a UTF-8 BOM (read with `utf-8-sig`). The IXI HH voxel height is 1.200004 mm, so the "voxels larger than 1.2 mm" warning has a 0.01 mm tolerance. FreeSurfer inflated hemispheres each centre near x = 0 and overlap, hence the labelled 8 mm display separation.
- **Test layout**: the integration fixture lives in `tests/integration/test_real_datasets.py`. A second `conftest.py` shadowed the unit-test `conftest` module and broke collection of four unit-test files.
