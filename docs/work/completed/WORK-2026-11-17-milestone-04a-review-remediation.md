# WORK-2026-11-17-milestone-04a-review-remediation: Milestone 04A review remediation

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0022-milestone-04a-review-remediation.md`

## Objective

Correct the replay, baseline, finding-provenance, and file-import defects reproduced by the Milestone 04A review, and cover them with tests.

## Scope

In scope: gap indexes in `ReplayEegAdapter`, pause deadlines, stream-relative baseline lock, stale findings, recording-id seek, EDF EEG-only µV conversion, replay status copy, history expiry count, acquisition-health gate, llama cancel on session change, measurement-backed answers, session error text, `manifestSha256`, and the louder occipital blink comparison.

Non-goals of the code change: changing EEG protocol v2, downloading weights, and measuring llama time to first token. The owner accepted the ADRs afterward.

## Acceptance Criteria

- [x] A declared gap is replayed as an index hole, and a moving clock during pause does not make the next block immediate.
- [x] Seeking to the alpha finding can lock a baseline from the samples collected on the new stream.
- [x] Older findings become stale, and an evidence click does not seek a different recording.
- [x] EDF conversion keeps EEG microvolts and drops non-EEG rows. File replay is not labeled as a live device measurement.
- [x] Engine ruff/pytest and desktop test, typecheck, and lint were run. Results are below.

## Implementation Summary

Replay recomputes the sample index at each present run and adds paused time to later deadlines. The analyzer measures windows and the 20 s baseline from the current stream's first index. A new stream marks older findings stale. Seek requires a matching recording id. Answer text is built from stored channel measurements. EDF import omits non-EEG channels. The manifest checksum covers the metadata that interprets the sample blob. A gap of at most 5% is still mean-substituted inside the periodogram, and the template sentence says so.

## Validation Evidence

- `cd services/neuro-engine && uv run ruff check .` — All checks passed.
- `cd services/neuro-engine && uv run pytest -q --tb=line` — 443 passed, 4 deselected, 1 failed. The failure was `test_data_root_inside_a_git_tree_must_be_ignored`: `git init` returned EPERM inside the sandbox (`Operation not permitted` on `.git/hooks`).
- Re-run of that test with the sandbox disabled — 1 passed.
- Probe after the fix: `expired 125`; seek from sample 2418 collected windows and `lock_baseline()` returned true; pause delay after a 5 s clock advance was `200000` µs; gap indexes skipped 40–49 and the next index was 50, last index 109.
- `yarn nx run-many -p @neuro-observatory/protocol,desktop -t test typecheck lint` — all six targets succeeded. Protocol targets were cache hits. Desktop test, typecheck, and lint ran.
- The pause refusal and replay status sentence were exercised in the desktop test renderer. A live browser session against a running engine was not opened.

## Risks and Follow-ups

The owner accepted ADR-0016, ADR-0017, ADR-0018, and `ADR-0022-milestone-04a-review-remediation` on 2026-11-17. Mean substitution of gaps at or below 5% can still bias a band-power estimate; the fraction is stored and the sentence discloses it. EDF discontinuities are still not imported as gaps. Phase 6 still has no measured time to first token or browser frame interval. Blink findings still store the frontal peak in `rmsUv`.

## Human Review

The owner accepted this remediation, together with ADR-0016, ADR-0017, and ADR-0018, on 2026-11-17.
