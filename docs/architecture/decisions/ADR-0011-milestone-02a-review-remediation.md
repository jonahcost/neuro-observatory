# ADR-0011: Milestone 02A independent review remediation

- Status: Accepted
- Date: 2026-10-30
- Decision Owner: Project owner (accepted 2026-10-30 in chat after selecting the unknown-unit, asset-identity and reconstruction-provenance policies)
- Related Work: `docs/work/completed/WORK-2026-10-30-milestone-02a-review-remediation.md`
- Supersedes: None

## Context

ADR-0010 delivered Milestone 02A, then an independent review compared the implementation with its accepted decision, completed work record and repository standards. The normal suite passed, but targeted probes reproduced defects that the existing tests missed:

- an acquisition record can embed different, path-traversing dataset identifiers and make later validation or writes escape the configured data root;
- an existing checksum-less IXI file is accepted by size and its current SHA-256 is then recorded as if it were the official tar member;
- anatomy preparation does not require source files to match acquisition or reconstruction provenance;
- equal vertex counts are treated as proof of cross-surface vertex identity even when face topology differs;
- unknown NIfTI units are exposed as millimetres, and conflicting qform/sform affines are silently reduced to nibabel's selected affine and called scanner RAS;
- redirect targets bypass the download-host allowlist;
- the anatomy v1 validators accept root-escaping provenance paths, out-of-int32 label indices, contradictory acquisition provenance, ambiguous transforms and Python-only Unicode timestamps;
- a valid manifest with corrupt buffers remains catalogued and can be served with an immutable cache policy;
- asset IDs omit tool versions while the manifest timestamp makes regenerated manifest bytes differ;
- fixed temporary files and unlocked provenance read-modify-write operations are unsafe under concurrency; local imports validate a different snapshot from the one copied;
- MRI and browser response bodies have no decoded-size cap; client sibling requests continue after integrity failure; replaced GPU colour attributes are not explicitly reclaimed;
- real-data tests can reuse old prepared assets and therefore do not prove current preparation behavior.

The review also confirmed that EEG protocol v2, sample timing, drop/duplicate handling and the acquisition event loop were unchanged. Anatomy remains separate from EEG and is labelled as structural anatomy with no activity overlay.

## Decision

Accepted. The owner selected the following policy choices:

1. **Unknown NIfTI units:** reject by default. An explicit millimetre assumption is allowed only through a named CLI/import option and is recorded as a user declaration; no code silently relabels unknown units as mm.
2. **NIfTI transforms:** compare valid qform and sform matrices and fail on material disagreement. Preserve the selected transform source and xform code; call it scanner RAS only for scanner-coded transforms and otherwise report the truthful world/reference frame.
3. **Asset identity:** retain a stable derivation ID rather than minting a new ID on every rebuild. Include output-affecting tool versions and pipeline version in the identity. Buffers must be deterministic; `preparedAtUtc` is operational manifest metadata and is not claimed byte-deterministic.
4. **Source provenance gate:** raw/imported sources must match their acquisition record before preparation. Externally reconstructed derivatives require a versioned reconstruction record containing input hashes, tool/version, command/configuration, output hashes and explicit QC status before they can be prepared.
5. **Anatomy contract v1 hardening:** treat validation tightening as correction of already documented v1 invariants, not a new wire version. Add shared fixtures so TypeScript, JSON Schema and Python classify every corrected edge case identically.
6. **Dataset publication:** validate and hash staged snapshots, publish atomically without following symlinks, reject unsupported OpenNeuro checksum formats, compare checksum-less existing files with recorded SHA-256, validate every redirect target, and lock per-dataset provenance updates.
7. **Geometry integrity:** require identical face topology across pial/white/inflated surfaces per hemisphere, reject zero-area/reversed/non-closed meshes where the contract claims outward closed FreeSurfer surfaces, and verify declared bounds match decoded extrema.
8. **Serving and client integrity:** do not list corrupt assets as healthy or convert corruption into an empty-state message. Verify file size/hash before immutable serving, bound client reads, bypass cache after integrity failure, cancel sibling loads after one failure, and reclaim replaced GPU attributes.
9. **Privacy and resource limits:** reject wildcard anatomy CORS, create restricted personal-data paths/files with private permissions where the platform supports them, cap GraphQL listings, tar members, voxel counts/decoded bytes and anatomy response sizes, and avoid normal CLI disclosure of absolute personal data roots.
10. **Evidence correction:** force clean real-data asset generation in integration tests; test the digitization/fiducial/parcellation claims that remain acceptance criteria; amend ADR-0010 and its completed work record with factual corrections rather than rewriting its historical decision.

No EEG stream schema or acquisition behavior changes. No real MRI, EEG or downloaded dataset content enters Git or tests.

## Alternatives Considered

- **Retain warnings and documentation only:** rejected because the reproduced failures allow false units/frames, unverified raw inputs, path escape and provenance loss.
- **Create anatomy contract v2 for every stricter validation rule:** rejected because the newly rejected documents already violate v1's prose invariants and were never emitted by the producer. A new version would legitimize malformed v1 documents without adding a useful representation.
- **Require known NIfTI units with no override:** scientifically safest but unnecessarily blocks legitimate legacy files whose user can explicitly and traceably attest millimetres.
- **Keep derivatives warning-only:** rejected because source-estimation assets need reproducible reconstruction and QC provenance, not an optional warning.
- **Hash preparation time into the asset ID:** rejected because identical derivations would create unbounded duplicate assets and defeat stable references.

## Consequences

Benefits: path containment, immutable-source enforcement, truthful units/frames, stronger vertex identity, reproducible reconstruction lineage, recoverable cache failures and tests that exercise current code. Personal anatomy gets stronger local permissions and origin validation.

Costs: stricter validation may reject previously tolerated malformed manifests or legacy NIfTI files until the user supplies an explicit mm assumption. Existing prepared assets may need regeneration because the derivation identity includes tool versions and the pipeline version advances. Reconstruction imports require an additional provenance record and QC declaration. Hash verification and bounded streaming add I/O and implementation complexity.

Scientific limitation: the MRI check establishes structural-volume suitability, not that image contrast is truly T1-weighted. The user or dataset metadata must attest modality. Passing geometry checks does not replace visual FreeSurfer QC.

Compatibility: anatomy schema version remains 1, but accepted input narrows to the documented contract. EEG protocol v2 and its endpoint are unchanged.

## Validation and Rollback

Validation:

- shared invalid/valid fixtures for path segments, int32 labels, timestamps, acquisition source combinations, transform uniqueness/invertibility and exact bounds;
- synthetic NIfTI tests for explicit/unknown units, qform/sform agreement and scanner/aligned/MNI codes;
- tampered raw and missing/failed reconstruction provenance tests;
- mixed topology, reversed winding, zero-area and non-closed surface tests;
- same-size IXI substitution, unknown OpenNeuro checksum, cross-host redirect, symlink/TOCTOU and concurrent provenance tests;
- corrupt catalog/buffer, immutable-cache recovery, oversized response, sibling cancellation and repeated atlas-toggle disposal tests;
- forced fresh real-data preparation when an authorized local data root is available;
- full Nx lint/test/typecheck/build, generated-contract check, engine pytest/ruff, governance checks and `git diff --check`.

Rollback is a unit revert of this remediation. Existing ADR-0010 assets remain regenerable from verified sources. If strict NIfTI handling blocks a legitimate file, the supported fallback is the explicit, provenance-recorded millimetre assumption—not silent guessing.
