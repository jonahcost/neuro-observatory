# WORK-2026-11-17-live-eeg-replay-and-findings: Replay recordings and local EEG findings

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0016-live-eeg-replay-and-findings.md`

## Objective

Replay a deterministic synthetic alpha-step recording through the existing EEG protocol v2 visualizer, and publish versioned scalp band-power findings plus typed commands, without changing the default synthetic stream hash.

## Scope

In scope: `recording.v1`, `ReplayEegAdapter`, `SessionController`, the band-power analyzer tapped after accepted blocks, `assistant.v1`, loopback `/api/assistant/v1`, the inspector assistant panel, and emphasize / seek / marker / baseline / display-mode commands.

Non-goals: changing EEG v2 or anatomy v1, downloading model weights, enabling a blink classifier, OpenBCI, and push-to-talk.

## Acceptance Criteria

- [x] The alpha-step recording replays through protocol v2. Gaps stay gaps. The default synthetic configuration hash is unchanged.
- [x] A posterior alpha step emits an O1/O2 finding with µV², dB, and synthetic provenance. Flatline and a large gap do not emit a qualified band-power finding.
- [x] Seek on a live synthetic stream is refused. Replay seek opens a new stream id. Ambiguous and unknown findings do not move the source.
- [x] The desktop assistant panel selects the finding's primary channel on the existing EEG socket and does not seek a synthetic source.
- [x] Protocol and engine tests, desktop tests, typecheck, and lint were run. Results are below.

## Implementation Summary

Recording files live under the engine data root. Replay replaces the single-use adapter and starts a new stream. The analyzer keeps a 60 s history, a 2.0 s Hann periodogram, and a 20 s median baseline. Findings store summaries, not samples. The desktop panel polls `GET /api/assistant/v1/snapshot` and posts commands to the engine. Evidence selection uses one primary channel for `aria-pressed` and the finding's channel set for emphasis. A waveform highlight is drawn only while that sample-index range is still in the 10 s ring.

## Validation Evidence

- `cd services/neuro-engine && uv run ruff check .` — All checks passed.
- `cd services/neuro-engine && uv run pytest -q --tb=line` — 434 passed, 4 deselected, 1 warning in 6.28s.
- `yarn nx run-many -p @neuro-observatory/protocol,desktop -t test typecheck lint` — all six targets succeeded.
- `yarn nx run @neuro-observatory/protocol:generate-types` — wrote `assistant.v1.ts`. The protocol test confirms it matches the schema.

## Risks and Follow-ups

ADR-0016 stays Proposed until the owner marks it Accepted. The governance PR check requires that status, so this branch is not merge-ready until then. EEGMMIDB import is manual and is not part of CI. Renderer frame interval was not measured in a browser rAF loop; see the benchmark record.

## Human Review

The owner directed implementation of the 04A plan on 2026-11-17. This record does not mark ADR-0016 Accepted.
