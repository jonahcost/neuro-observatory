# WORK-2026-10-30-milestone-02a-review-remediation: Milestone 02A independent review remediation

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0011-milestone-02a-review-remediation.md`

## Objective

Resolve the confirmed Milestone 02A review defects so anatomy assets are prepared only from contained, provenance-verified sources; units, coordinate frames and vertex identity are truthful; dataset and asset publication is atomic and recoverable; and the accepted records match tested behavior.

## Scope

In scope:

- `services/neuro-engine`: dataset path containment, checksums, redirects, staging, locking, private permissions, acquisition/reconstruction provenance, NIfTI unit/xform/resource validation, surface topology, deterministic derivation identity, asset catalog/serving integrity and CLI behavior.
- `packages/protocol`: anatomy v1 schema and semantic parity for paths, timestamps, int32 labels, transforms, acquisition provenance and bounds.
- `apps/desktop`: bounded/cancellable buffer loading, cache recovery and GPU attribute cleanup.
- synthetic unit/contract/API/UI tests, clean real-data integration behavior, ADR-0010/work-record corrections and operating documentation.

Non-goals: EEG v2 changes; source localization; FreeSurfer/FastSurfer execution; DICOM ingestion; new network services; dependency upgrades; real-data downloads or hardware experiments.

Dependencies: owner acceptance of ADR-0011. Real-data reruns require an already authorized local public-dataset root; no private MRI or EEG will be inspected.

## Acceptance Criteria

- [x] Acquisition records cannot redirect reads or writes outside the data root and must match the requested dataset/version.
- [x] Existing checksum-less files match recorded SHA-256; unsupported OpenNeuro checksums and disallowed redirects fail before publication.
- [x] Imports/fetches use validated staging snapshots, atomic no-overwrite/no-follow publication and coordinated provenance updates.
- [x] Anatomy preparation rejects acquisition mismatch or missing reconstruction provenance and verifies topology, winding/closure, bounds and source identity.
- [x] Unknown NIfTI units fail unless an explicit mm assumption is recorded; conflicting qform/sform fails; selected xform semantics are reported truthfully with bounded voxel loading.
- [x] Anatomy v1 TS/Python/schema fixtures agree for every corrected protocol edge case.
- [x] Stable asset derivation IDs include output-affecting tool/pipeline versions; docs claim deterministic buffers, not volatile manifest bytes.
- [x] Corrupt assets are not healthy catalog entries or immutable responses; desktop retry recovers, reads are bounded/cancelled and GPU buffers are reclaimed.
- [x] Real-data tests force current-code generation and verify retained EEG/parcellation acceptance claims, or record an explicit authorized-environment skip.
- [x] Full lint, tests, typecheck, build, generated files, governance and diff hygiene pass; no restricted files are tracked.

## Implementation Summary

- Hardened anatomy v1 in JSON Schema, TypeScript and Python: safe relative provenance paths, int32 label bounds, real ASCII UTC calendar timestamps, acquisition-kind consistency, transform uniqueness/invertibility, exact decoded bounds and deep serialization revalidation. Shared fixtures run in both languages.
- Reworked dataset integrity: constrained record identity, merge-under-OS-lock provenance writes, private paths/files, per-redirect and final-URL allowlisting, bounded OpenNeuro and IXI reads, staged validation before no-overwrite publication, recorded-hash checks for checksum-less IXI files, fsaverage revalidation and explicit symlink rejection.
- Added versioned reconstruction provenance (source/output hashes, tool/version, privacy-safe command summary and QC status). Preparation verifies acquisition and reconstruction hashes and requires passed QC.
- Corrected NIfTI behavior: unknown units reject unless `--assume-mm` is explicitly recorded; qform/sform agreement is checked by absolute world displacement; selected xform frames are named truthfully; voxel and decoded-byte limits are enforced.
- Strengthened surfaces/assets: zero-area, open, inconsistent-winding and disconnected meshes fail; corresponding surface face arrays must match; stable 128-bit derivation IDs include tool versions; bounds derive from serialized float32 data; corrupt assets cannot be catalogued or served immutable.
- Hardened loopback serving and desktop loading: explicit loopback HTTP(S) CORS, bounded JSON/buffer streaming, one cache-reload integrity retry, sibling cancellation, verified byte snapshots and geometry disposal on atlas changes. Normal CLI output no longer exposes the absolute data root.
- Corrected anatomy, engine, protocol and reconstruction documentation, and added factual post-acceptance notes to ADR-0010 and its completed work record.

## Validation Evidence

Pre-change independent review evidence:

- normal Nx lint/test/typecheck/build passed; engine 354 tests, protocol 89 tests and desktop 34 tests passed;
- governance and generated-type checks passed;
- integration suite skipped four tests because no data root was configured;
- `git diff --check main...HEAD` failed on trailing whitespace in an invalid JSON fixture;
- targeted temporary-directory probes reproduced path escape, checksum re-baselining prerequisites, tampered-source preparation, topology mismatch acceptance, unknown-unit relabelling, qform/sform conflict acceptance, non-deterministic manifest bytes and corrupt-asset cataloguing.

Post-change evidence (final runs on 2026-10-30):

- `NX_DAEMON=false yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache --output-style=static` — exit 0. Protocol 98 tests, desktop 37 tests, engine 398 passed / 4 integration deselected; ESLint, Ruff, TypeScript checks and Vite build passed. Vite retained the known 1.326 MB chunk-size warning.
- `yarn nx run @neuro-observatory/protocol:check-generated --skip-nx-cache` — exit 0; generated types up to date.
- `env -u NEURO_ENGINE_DATA_DIR uv run pytest -m integration tests/integration -v` — exit 0; four tests skipped with the documented missing-data-root reason. No authorized data root was configured, so no real MRI/EEG/public dataset was opened. The tests now clone recorded public inputs into an isolated root, require `prepared.created`, and assert retained parcellation/digitization facts when enabled.
- `python3 tools/governance/check_governance.py --all` — passed.
- `python3 -m unittest discover -s tools/governance/tests` — 5 tests passed.
- `git diff --check main` — exit 0.
- `git status --short` and `git diff --name-only main` — reviewed; no restricted data files are present. The branch remains intentionally uncommitted after this remediation.

## Risks and Follow-ups

Stricter v1 validation can reject previously tolerated malformed documents. Existing assets require regeneration after the pipeline/identity version change. Reconstruction provenance records a human QC declaration but does not automate or certify QC. The MRI check cannot infer T1 contrast from voxel values; modality remains declared provenance. Full real-data verification remains skipped until an already authorized public-dataset root is explicitly configured. The desktop production bundle remains above Vite's 500 kB advisory threshold.

Rollback: revert this remediation as one unit and retain ADR-0010 behavior; downloaded raw data is not migrated or modified in place.

## Human Review

2026-10-30: the owner selected strict unknown-unit handling with an explicit recorded mm override, stable derivation IDs with deterministic-buffer (not timestamped-manifest) claims, and mandatory versioned reconstruction provenance with QC status. The owner then accepted ADR-0011 as a whole and authorized implementation.
