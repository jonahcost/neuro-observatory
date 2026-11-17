# WORK-2026-11-17-waveform-viewer-review-remediation: Waveform viewer review remediation

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0013-waveform-viewer-review-remediation.md`

## Objective

Correct the Milestone 03A waveform defects confirmed by re-reading the buffer and view: provenance identity, restart-hole retention, index placement, restart caption, one-sample strokes, and overlapping blocks.

## Scope

In scope:

- `apps/desktop/src/stream/waveformBuffer.ts` and `WaveformView.tsx`, plus their tests.
- Clarification notes in ADR-0012, `docs/architecture/OVERVIEW.md`, and the 03A work record.
- This work record and ADR-0013.

Non-goals: protocol, engine, reconnect policy, ±100 µV scale, the same-id half-sample clock rule, paint decimation at the 64 × 20000 cap, and a new browser smoke of the dev servers.

Dependencies: ADR-0012 and the staged 03A viewer. The project owner authorized applying the justified review fixes on 2026-11-17.

## Acceptance Criteria

- [x] A same-montage device stream after a synthetic stream clears the rings and drops the synthetic sentence. The reverse sets the sentence again. A reference or channel-type change also clears the rings. — `waveformBuffer.spec.ts`.
- [x] A restart block as long as the window leaves the observed hole in front of that block's tail. — `waveformBuffer.spec.ts` ("keeps a visible restart hole…").
- [x] Empty slots follow the sample-index gap. A larger `droppedSamplesBefore` does not add slots. A forward-time overlap appends only the new tail, and a fully stale block is ignored. — `waveformBuffer.spec.ts`.
- [x] "New stream" is only the new-`streamId` caption. A same-id backwards clock has its own sentence. The caption clears once later samples push the hole out. A one-sample run emits a stroke. — `WaveformView.spec.tsx` and `waveformBuffer.spec.ts`.

## Implementation Summary

- Layout identity now includes provenance kind, per-channel reference, and channel type. A change allocates new rings and sets `synthetic` from that metadata.
- A clock-domain break keeps `min(gap, capacity - 1)` empty slots, then the newest samples that fit. `restartCause` is `new-stream` or `source-clock`. Later writes clear it when the hole leaves the window.
- In-stream gaps use `firstSampleIndex - nextSampleIndex`. Overlap appends only indexes at or after `nextSampleIndex`.
- A one-point run adds a one-pixel segment before `stroke`.
- The same-id half-sample rule from ADR-0012 is unchanged. `droppedSamplesBefore` is no longer a second gap length.

## Validation Evidence

| Command | Result |
| --- | --- |
| `yarn nx test desktop --skip-nx-cache -- src/stream/waveformBuffer.spec.ts src/stream/WaveformView.spec.tsx src/app/app.spec.tsx` | Exit 0. 3 files, 25 tests passed (buffer 20, view 3, app 2). |
| `yarn nx run-many -t lint test typecheck --projects=desktop --skip-nx-cache --output-style=static` | Exit 0 in about 1.5 s. Desktop lint and `tsc -p tsconfig.app.json --noEmit` passed. Full desktop Vitest: 8 files, 61 tests passed. |
| `yarn tsc -p apps/desktop/tsconfig.spec.json --noEmit` | Exit 0. |
| `python3 tools/governance/check_governance.py --all` | Exit 0. "Governance check passed. Human review and scientific/safety validation still required." |
| `git diff --check` | Exit 0. |

Not run: the full monorepo `lint test typecheck build` gate, engine pytest, and a new browser smoke. The code change is the desktop viewer. The previous 03A smoke remains the manual engine-plus-desktop check and is corrected where it overstated a blank history.

## Risks and Follow-ups

A same-id source clock that steps backwards by more than half a sample still opens a clock domain of at least 250 ms. That is the ADR-0012 rule; a later device clock may want its own decision. Painting every sample at 64 channels × 20000 slots can still be heavy on the main thread. The ±100 µV lanes still clip larger amplitudes. The viewer is not a recording.

## Human Review

The project owner authorized applying the justified Milestone 03A review fixes on 2026-11-17. No separate policy choice was required: the same-id half-sample clock rule stays accepted ADR-0012, and the caption now distinguishes it from a new stream. ADR-0013 is Accepted on that authorization.
