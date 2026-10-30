# ADR-0004: Keep raw recordings separate from derived visualization

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

EEG processing parameters and models evolve; raw recordings should remain reproducible and usable for later analysis.

## Decision

Persist time-stamped raw device measurements with metadata, gaps, reference, hardware settings and calibration; derived data is separate/versioned. Replay enters the same processing abstraction as live data.

## Alternatives Considered

Only store processed features or renderer frames (cannot fully reprocess). Use UI state as data truth (lossy and fragile).

## Consequences

More disk consumption and metadata management in exchange for reproducibility and crash isolation.

## Validation and Rollback

Use known synthetic streams to test equality of replayed inputs, gap reports, and recorder independence when the UI dies. Roll back derived processing without modifying raw files.
