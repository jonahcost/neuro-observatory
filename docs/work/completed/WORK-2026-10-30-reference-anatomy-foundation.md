# WORK-2026-10-30-reference-anatomy-foundation: Milestone 02A: Reference neuroimaging datasets and cortical anatomy viewer

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0010-reference-anatomy-foundation.md`

## Objective

The desktop app renders real FreeSurfer cortical geometry (fsaverage by default, then ds000248 `sub-01`), loaded from a provenance-tracked, offline-capable dataset store through a versioned anatomy asset contract. Coordinates, units and vertex identity are preserved. The same path later accepts the owner's own 3T T1 reconstruction.

## Scope

In scope:

- `services/neuro-engine`:
  - `neuro_engine/datasets/`: catalog, storage root, verified resumable downloads, fsaverage via MNE, ds000248 `1.2.4` via the OpenNeuro API, IXI import and single-member fetch, local imports, `acquisition.json`, validation.
  - `neuro_engine/anatomy/`: volume and surface I/O (nibabel), transforms, parcellations, asset preparation, MRI checks, EEG inspection (MNE, optional).
  - `neuro_engine/protocol/anatomy_v1.py`: Pydantic mirror.
  - `neuro_engine/api/anatomy.py`: read-only asset endpoints and CORS.
  - `neuro_engine/cli.py`: `neuro-engine datasets|anatomy ...` subcommands.
  - Settings `NEURO_ENGINE_DATA_DIR`; pytest markers; `test-integration` Nx target; dependencies `nibabel` plus the optional `neuroimaging` extra.
- `packages/protocol`: `schemas/anatomy-asset.v1.schema.json`, generated types, `parseAnatomyAsset` and `parseAnatomyCatalog`, fixtures `fixtures/anatomy-v1/`, multi-schema `generate-types`.
- `apps/desktop`: `src/anatomy/` (client, hook, scene state, renderer adapter, panel) replaces the placeholder sphere. The EEG stream panel is unchanged.
- Docs: `docs/architecture/ANATOMY.md` (layers, coordinate frames, EEG integration path), an `OVERVIEW.md` update, the engine README (setup, commands, disk, storage, adding subjects, personal MRI), `pipelines/mri-reconstruction/README.md`, and protocol README entries.

Non-goals: running FreeSurfer or FastSurfer; DICOM import; head↔MRI registration; electrode positions; BEM, forward or inverse models; source estimates or any activity overlay (synthetic or real); EEG playback from ds000248; mesh decimation and LOD; volume rendering or slice views; Tauri packaging; changes to EEG protocol v2 or acquisition.

Dependencies: owner acceptance of ADR-0010 and the choices it marks; network approval for the verification downloads (fsaverage 0.43 GB, ds000248 anatomy profile 0.19 GB, IXI single member 10 MB).

Delivery order (one chunk and PR, implemented and verified in this order): M1 datasets and storage → M2 anatomy I/O and assets → M3 fsaverage in the viewer → M4 ds000248 `sub-01` → M5 IXI HH T1 validation and documented FreeSurfer workflow → M6 integration contracts and docs. If time runs out, unfinished milestones are recorded as follow-ups, not shipped as placeholders.

## Acceptance Criteria

- [x] `neuro-engine datasets list` shows fsaverage, ds000248 and IXI with version, license, size and acquisition status. Unknown dataset or subject gives an actionable error.
- [x] `datasets fetch fsaverage` and `datasets fetch ds000248` (anatomy profile) are idempotent and resumable. Every file is verified against an upstream checksum or a recorded SHA-256, and `acquisition.json` is written. A checksum or size mismatch fails without leaving a "verified" file. Downloads over 500 MB need `--confirm-large`.
- [x] `datasets fetch ixi --subject IXI012-HH-1211` (if approved) or `datasets import ixi <file>` stores one HH T1. `anatomy check-mri` reports 3D shape, voxel size, orientation and affine validity. Unsupported formats (`.dcm`, `.img`, 4D) are rejected with guidance.
- [x] `anatomy prepare <subject>` writes a deterministic asset (same inputs give the same `assetId` and bytes). Pial, white and inflated for lh and rh, with `aparc` labels. Counts, index range, finite coordinates and bounds are validated; the frame is FreeSurfer surface RAS in mm; the surface-RAS→scanner-RAS transform is included.
- [x] Manifest fixtures are classified identically by TS (Ajv plus semantic layer) and Python (Pydantic plus `jsonschema`). `check-generated` passes.
- [x] The engine serves catalog, manifest and files on loopback. Path traversal and unlisted names return 404; disallowed origins get no CORS headers; the EEG endpoints still behave as before.
- [x] The desktop renders both hemispheres of fsaverage with orbit, pan and zoom. Switching to ds000248 `sub-01` works without a restart. Loading, empty (no prepared assets, with the command to run), error and ready states all work. Template, reference-subject and personal labels are visible, and so are "No activity overlay" and "EEG stream not mapped to anatomy". (Orbit was exercised in the browser; pan and zoom are enabled on the same `OrbitControls` but were not exercised separately. The personal label is unit-tested only: no personal subject exists.)
- [x] For ds000248 `sub-01`: the T1w voxel grid matches FreeSurfer `rawavg.mgz`, BIDS subject and FreeSurfer subject agree, the FIF has 60 EEG channels, and digitization and landmark availability are reported. Opt-in integration tests cover this.
- [x] No test needs network or real data in CI. Integration tests skip with a reason when data or MNE is missing.
- [x] `yarn nx run-many -t lint test typecheck build`, engine pytest/ruff and governance checks pass. No restricted files are tracked.

## Implementation Summary

All six milestones (M1–M6) were implemented in this chunk. Nothing is committed.

- **Engine datasets** (`services/neuro-engine/src/neuro_engine/datasets/`): `catalog.py` (fsaverage, ds000248 `1.2.4`, IXI, local; licences, pinned versions, site facts), `storage.py` (per-user root, Git-ignore guard), `download.py` (stdlib HTTP, allow-listed hosts, resume via `Range`, size cap, MD5/git-blob-SHA-1/SHA-256 verification, ranged member reads), `integrity.py`, `provenance.py` (`acquisition.json`, `verify_record`), `fsaverage.py` (MNE with in-process `SUBJECTS_DIR`), `openneuro.py` (GraphQL listing, profiles, path sanitising), `ixi.py` (tar-header walk, single-member fetch, gzip CRC check, local import), `local.py` (personal MRI and FreeSurfer import), `subjects.py` (discovery and consistency checks), `eeg.py` (metadata-only inspection via mne-bids).
- **Engine anatomy** (`anatomy/`): `volumes.py` (`check-mri`), `surfaces.py`, `transforms.py`, `assets.py` (deterministic content-addressed assets, `AssetStore`, verification).
- **Contract**: `packages/protocol/schemas/anatomy-asset.v1.schema.json`, generated types, `src/anatomy.ts`, fixtures `fixtures/anatomy-v1/`, multi-schema `generate-types`; Pydantic mirror `neuro_engine/protocol/anatomy_v1.py`.
- **API and CLI**: `api/anatomy.py` mounted at `/api/anatomy/v1` (GET only, CORS allowlist, manifest-listed files only); `cli.py` (`neuro-engine datasets|anatomy ...`); `NEURO_ENGINE_DATA_DIR`; `nibabel` runtime dependency; `neuroimaging` extra (`mne`, `mne-bids`); pytest `integration` marker and `neuro-engine:test-integration`.
- **Desktop** (`apps/desktop/src/anatomy/`): verifying client, cancellable loading hook, scene geometry (RAS→Three.js, inflated display gap, framing, atlas colours), `CorticalSurfaceView`, `AnatomyViewer` (subject/surface/atlas selection, Refresh subjects, loading/empty/error/ready, provenance and licence, "No activity overlay"), typed `CorticalOverlay` without a producer. The placeholder sphere is gone; the EEG status panel is unchanged.
- **Docs**: `docs/architecture/ANATOMY.md`, `OVERVIEW.md`, engine README (setup, storage, disk use, commands, adding subjects, personal MRI, tests), `pipelines/mri-reconstruction/README.md`, protocol README.
- Deviations from the ADR text and real-data findings are listed in ADR-0010 "Implementation Notes".

## Validation Evidence

Baseline before any change (2026-10-30, `main` at `5356474`): `NX_DAEMON=false yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache` passed: 9 tasks across `neuro-engine`, `@neuro-observatory/protocol` and `desktop`, 5.7 s, exit 0. Nx could not create plugin-worker sockets in the agent sandbox, so plugins ran in the main process. This is an environment warning, not a failure.

Research probes actually run (read-only network, no dataset content downloaded):

- OpenNeuro GraphQL `dataset(id: "ds000248")`: latest snapshot `1.2.4`, CC0, DOI `10.18112/openneuro.ds000248.v1.2.4`.
- Recursive `snapshot(tag: "1.2.4").files(tree)` listing: 1 229 files, 2 073 274 143 bytes. Anatomy profile: 30 files, 193.6 MB.
- Sidecars fetched: `sub-01_T1w.json` (landmarks only), `sub-01_coordsystem.json` (ElektaNeuromag, m), `..._meg.json` (60 EEG channels, 600.615 Hz, 60 Hz line), `README` (Siemens 1.5 T Sonata, MPRAGE; recon-all command).
- MNE 1.13.2 wheel source: fsaverage archive URLs and MD5s; `set_config` side effect. OSF `Content-Length`: 195 858 394 and 231 112 532 bytes.
- IXI: `IXI-T1.tar` 4 840 816 640 bytes, `Accept-Ranges: bytes`. Two 512-byte header range reads: member 0 `IXI002-Guys-0828-T1.nii.gz`, member 1 `IXI012-HH-1211-T1.nii.gz` (10 120 330 bytes at offset 6 944 256). License CC BY-SA 3.0 (site text). HH scanner page: Philips Intera 3T T1 parameters.
- PyPI: `mne` 1.13.2 (BSD-3), `nibabel` 5.4.2 (MIT), `mne-bids` 0.20.0 (BSD-3), `openneuro-py` 2026.9.1 (GPL-3.0-only).

### After implementation (2026-10-30, macOS, data root `~/Library/Application Support/NeuroObservatory`)

Automated checks, final run after all edits:

| Command | Result |
| --- | --- |
| `NX_DAEMON=false yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache` | Exit 0. Protocol 89 tests, desktop 34 tests, engine 354 passed / 4 deselected (integration), ruff clean, typecheck and build pass. Vite warns that the desktop chunk is 1 323 kB (367 kB gzip); not compared with the baseline |
| `yarn nx run @neuro-observatory/protocol:check-generated --skip-nx-cache` | Exit 0 (after regenerating types for the edited `sources.path` description) |
| `uv run pytest` (engine) | 354 passed, 4 deselected |
| `uv run ruff check .` (engine) | All checks passed. (`ruff format --check` would reformat 51 files, including untouched baseline files; it is not a project gate) |
| `NEURO_ENGINE_DATA_DIR=… uv run --extra neuroimaging pytest -m integration tests/integration -v` | 4 passed: fsaverage end-to-end, ds000248 `sub-01` end-to-end, ds000248 EEG metadata, IXI HH T1. Includes outward-orientation and plausible enclosed volume for every pial/white hemisphere |
| Same, without `NEURO_ENGINE_DATA_DIR` | 4 skipped with "set NEURO_ENGINE_DATA_DIR …" |
| `python3 tools/governance/check_governance.py --all` | Passed |
| Change-set simulation (`check_change_set` over `git diff HEAD` plus untracked files, 99 paths) | Before acceptance: no restricted paths; failed only on "ADR-0010 Status must be Accepted" and "requires a completed WORK record". After owner acceptance and moving this record: no issues; `--all` passed again |
| `python3 -m unittest discover -s tools/governance/tests` | 5 tests OK |

A failure found and fixed during final verification: `tests/integration/conftest.py` shadowed the engine's `tests/conftest.py` (both import as `conftest`), so four unit-test modules failed to collect in the full `uv run pytest`. The fixture moved into the integration module and that file was deleted.

Real downloads (owner-authorised):

| Dataset | Command | Result |
| --- | --- | --- |
| IXI012-HH-1211 | `neuro-engine datasets fetch ixi --subject IXI012-HH-1211 --accept-license` | 2.2 s; 10 120 330 bytes at tar data offset 6 944 768; gzip CRC verified; sha256 `073461dc…800c0e`. 256×256×150, 0.9375×0.9375×1.2 mm, PSR, oblique, int16 |
| ds000248 `1.2.4` anatomy | `neuro-engine datasets fetch ds000248` | 21 s; 36 files, 201 537 926 bytes; every file matched its upstream MD5 or git blob SHA-1 |
| fsaverage | `uv run --extra neuroimaging neuro-engine datasets fetch fsaverage --accept-license` | 25 s; both OSF archives via MNE; 761 MB on disk; 15 files recorded; no `~/.mne` created |

`neuro-engine datasets validate` matched every recorded file for all three datasets. `datasets check-subject ds000248/sub-01`: `rawavg-matches-t1`, landmarks inside the volume, 60 EEG channels at 600.614990234375 Hz. `inspect-eeg`: 60 EEG + 316 other channels, 277.7 s, 60 Hz line, 61 digitized EEG points, LPA/NASION/RPA, 78 head-shape points, bad `EEG 053`, 320 annotations, `source_localization_ready: false`. IXI: `no-reconstruction` (no surfaces).

Prepared assets (`anatomy prepare`, about 0.2 s each; `anatomy verify` clean):

- `fsaverage-cf80561a66d16503`: 36 MB, 163 842 vertices per hemisphere, transforms to `scanner-ras` and `mni305-ras` (identity), atlases aparc and aparc.a2009s.
- `ds000248-sub-01-bd1cfa30e28131ce`: 37 MB, lh 158 443 / rh 161 391 vertices, `c_ras` (−5.27, 9.04, −27.29) mm agreeing with `orig.mgz`, atlases aparc, aparc.a2009s, aparc.dktatlas.

Live end-to-end check, with the engine (`uvicorn --reload`, 127.0.0.1:8000) and Vite dev server (:4200) already running in the owner's session and reloaded with this code:

- `/api/anatomy/v1/catalog` defaulted to fsaverage; a buffer returned 200 with 1 966 104 bytes and `immutable`; a traversal path returned 404; CORS echoed `http://localhost:4200`.
- In the browser: fsaverage pial rendered (both hemispheres); switching to ds000248 `sub-01` worked without a reload; aparc colouring shows precentral (blue) directly anterior to postcentral (red) in a left-lateral view, i.e. the axis mapping is not mirrored; inflated showed both hemispheres separated after an orbit drag; the provenance panel showed "Reference subject — a public research participant's anatomy, not yours", "1.5 T, MPRAGE, Siemens Sonata 1.5T (source: dataset-readme)", the 8 mm display note, "anatomical labels, not activity", "No activity overlay…" and the CC0 licence. The EEG panel stayed "Connected · Live" (synthetic).
- Found and fixed during this check: the canvas did not shrink when the window narrowed (grid track min-content), fixed with `gridTemplateColumns: 'minmax(0, 1fr)'`; afterwards canvas 965 px in a 1044 px viewport, no horizontal overflow.
- Pan and zoom were not exercised separately.

## Risks and Follow-ups

- The OpenNeuro GraphQL schema or S3 URL format may change: the downloader fails loudly with the dataset DOI as a manual fallback.
- The IXI range fetch depends on the archive layout and server range support (both verified 2026-10-30). Local import is always available.
- About 6 MB per hemisphere-surface may load slowly on weak GPUs. Decimation with vertex mapping is a follow-up.
- Follow-ups: FreeSurfer/FastSurfer reconstruction of the IXI HH T1 and later the personal MRI; head↔MRI registration from ds000248 landmarks and digitization; template and subject forward models; a source-estimate wire contract (new ADR); DICOM→NIfTI via dcm2niix; volume slice viewer.
- Known gaps after implementation: no reconstruction exists for IXI (documented only); no localization of any kind; the desktop bundle is 1.3 MB minified (three.js), not code-split; the OpenNeuro downloader depends on the GraphQL schema verified on 2026-10-30; ds000248's 1.5 T is from the README, not a sidecar; IXI scanner parameters are site-level; the personal-anatomy path is unit-tested with synthetic data only; `starlette.testclient` emits a deprecation warning about `httpx` (pre-existing).

Post-completion factual correction under accepted ADR-0011: the original criterion's phrase “same inputs give the same `assetId` and bytes” applies to the stable derivation ID and binary geometry/label buffers, not the timestamped manifest bytes. NIfTI world affines are named from their xform codes rather than universally called scanner RAS. External/personal reconstruction preparation now requires versioned input/output hashes and passed QC. The original validation results above remain historical evidence for ADR-0010; remediation evidence is recorded in `WORK-2026-10-30-milestone-02a-review-remediation.md`.

## Human Review

2026-10-30 (chat): the owner approved the ADR-0010 plan for implementation with the recommended option for every choice:

- per-user data root outside the repo
- stdlib OpenNeuro downloader (no `openneuro-py`)
- IXI single-member range fetch plus local import
- engine endpoints with CORS limited to the existing allowlist
- `nibabel` as a runtime dependency, `mne` and `mne-bids` in an optional extra
- FreeSurfer documented only, not run

The owner authorized the verification downloads: fsaverage (FreeSurfer license), the ds000248 `1.2.4` anatomy subset and IXI012-HH-1211 T1. ADR-0010 stays Proposed until the owner accepts it after reviewing the verification results.

2026-10-30 (chat), after the verification above: the owner accepted ADR-0010 as implemented, including its Implementation Notes. No commit, push or merge was authorized or performed.
