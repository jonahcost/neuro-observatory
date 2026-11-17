# WORK-2026-11-17-live-eeg-waveform-viewer: Live EEG waveform viewer

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0012-live-eeg-waveform-viewer.md`

## Objective

Show about 10 seconds of the existing simulated EEG stream as 16 stacked, labeled traces in the desktop app, with ingestion independent of rendering and a visible gap after the engine restarts.

## Scope

In scope:

- `apps/desktop`: `WaveformBuffer`, canvas `WaveformView`, wiring in `App`, and tests for channel order, rollover, gaps, restart, labels, and stroke breaks.
- `docs/architecture/OVERVIEW.md`: point `onBlock` at the waveform buffer.
- This work record and ADR-0012.

Non-goals: protocol or simulator changes, recording, replay, DSP, filtering, impedance, mapping EEG onto anatomy, chart-library dependencies, and physical-device acquisition.

Dependencies: protocol v2 and the synthetic 16-channel stream already on `main` (`43c0f38`). Owner approval of the plan and ADR-0012 (2026-11-17).

## Acceptance Criteria

- [x] Starting the engine and the desktop shows 16 labeled traces (`Fp1` through `Pz`) scrolling on one nominal-rate time axis, with synthetic provenance still visible. — Browser smoke below; `WaveformView.spec.tsx` (labels and synthetic caption); `app.spec.tsx` ("plots accepted blocks in stream channel order").
- [x] The buffer keeps `ceil(rate * 10)` samples per channel and drops the oldest on rollover. An in-stream index gap inserts that many empty slots and two finite runs. — `waveformBuffer.spec.ts` ("rolls over at 10 seconds…", "inserts one empty slot per missing sample…", "keeps a one-sample acquisition gap one sample wide").
- [x] Restarting the engine (new `streamId`, source timestamps near zero) leaves a visible hole of at least 250 ms and does not draw a line across it. Traces freeze while the socket is down and resume after the hole. — `waveformBuffer.spec.ts` (1.5 s hole of 188 slots keeps the old sample and the new sample on either side; 0 ms restart uses 31 slots; a 30 s outage stays inside the window); `WaveformView.spec.tsx` ("starts a new stroke after a gap…", stroke ops `move, line, move, line, stroke`); browser smoke below.
- [x] Samples do not enter React state. Incoming blocks do not each rerender the waveform chrome. A stream above 64 channels or 20 000 samples per channel is refused instead of truncated. — `waveformBuffer.spec.ts` ("does not notify chrome listeners for a contiguous block", "refuses a stream above the allocation cap…"); `app.spec.tsx` asserts the sample payload is not rendered as text. `EegStreamSnapshot` is unchanged and still has no sample field.
- [x] Focused desktop tests, `yarn nx run-many -t lint test typecheck build`, and the governance checks have been run, and the manual engine-plus-desktop smoke test has been recorded. — Validation Evidence.

## Implementation Summary

- `WaveformBuffer` keeps one ring per channel, `ceil(nominalSampleRateHz * 10)` slots (1250 at 125 Hz). Empty slots are NaN. `append` runs from `EegStreamClient.onBlock` and does not touch React. Chrome listeners fire only when the layout, the refusal, or the clock-domain flag changes.
- Inside one `streamId`, an index jump or `droppedSamplesBefore` inserts that many empty slots. A new `streamId`, or a same-id `firstSampleTimeUs` more than half a sample earlier, inserts the client-observed silence (at least 250 ms, at most the window). Reset monotonic times are not subtracted from the previous clock. A label, unit, or rate change clears the rings.
- `WaveformView` paints stacked lanes with `requestAnimationFrame` on a canvas pinned to a 480px grid cell. Each lane is ±100 µV. A NaN starts a new stroke. HTML labels follow metadata order. Status text uses the existing throttled snapshot. The figure says synthetic data is not a measurement, and it says when a new stream restarted the engine clock.
- The simulator, protocol, and WebSocket client were not changed. The default stream is already 16 channels at 125 Hz in `Fp1`…`Pz` order.

## Validation Evidence

| Command | Result |
| --- | --- |
| `yarn nx test desktop -- src/stream/waveformBuffer.spec.ts src/stream/WaveformView.spec.tsx src/app/app.spec.tsx` | Exit 0. 3 files, 15 tests passed (buffer 11, view 2, app 2). |
| `yarn tsc -p apps/desktop/tsconfig.spec.json --noEmit` | Exit 0. Nx `desktop:typecheck` compiles `tsconfig.app.json` only; this extra check covers the specs. |
| `NX_DAEMON=false yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache --output-style=static` | Exit 0 in 6.9 s on the final tree. Protocol 98 tests, desktop 51 tests, engine 398 passed / 4 deselected, ruff "All checks passed!", typecheck and Vite build passed. Known Vite chunk warning: desktop JS 1,334.20 kB (gzip 370.34 kB). Known pytest `StarletteDeprecationWarning` for `starlette.testclient`. |
| `python3 tools/governance/check_governance.py --all` | Exit 0. "Governance check passed. Human review and scientific/safety validation still required." |
| `python3 tools/governance/check_governance.py --base origin/main --head HEAD` | Exit 0 with the same message. `HEAD` is still `43c0f38`, so this comparison sees no committed diff. A dry run of `check_change_set` on the uncommitted paths (desktop view, buffer, app, ADR-0012, this completed record, overview) also passed. |

Manual smoke, 2026-11-17, synthetic stream only (not a measurement):

- `yarn nx run neuro-engine:serve` and `yarn nx serve desktop`, then `http://localhost:4200`.
- Status: "Connected · Live", "Synthetic signal — generated, not measured from a person (seed 0)", "16 × µV, reference synthetic, channel-major", "125 Hz nominal, 125.06 Hz measured by engine". Waveform labels were `Fp1, Fp2, F3, F4, F7, F8, C3, C4, Cz, P3, P4, T7, T8, O1, O2, Pz`. Page `scrollWidth` equalled `clientWidth` (1920). The plot cell was 480px tall.
- Fp1 trace pixels moved across a 600 ms sample. Stopping the engine set the waveform status to "Disconnected — reconnecting (attempt 4) · Waiting for data". A second Fp1 fingerprint 700 ms later was identical, while the last traces stayed on screen.
- Starting the engine again: on the transition back to "Connected · Live" (8.4 s after the waiter observed the outage), Fp1, Cz, and Pz ink occupied only the rightmost ~70 px of the 3568 px backing store, about one 25-sample block. The rest of each lane was blank, so the new stroke did not cross the outage. The caption read that the engine clock restarted and the new source timestamps were not joined to the previous clock. The anatomy region still listed prepared subjects.

The dev servers used for this check were left running: neuro-engine on `127.0.0.1:8000` and the desktop app on `http://localhost:4200`.

## Risks and Follow-ups

The ±100 µV lane scale clips larger future device amplitudes. Stored samples are unchanged. The display clock across an engine restart is an observed hole, not one monotonic timeline; an outage of about 10 s or more pushes the pre-restart traces out of the window, leaving blank space and then the new stream. In-stream gaps of a single sample can be narrower than a pixel. Recording and replay remain unimplemented.

Correction (ADR-0013): the 8.4 s smoke note says the rest of each lane was blank. A full 1250-sample ring keeps older samples until the observed hole reaches the window, so that sentence is the observation as written and is not evidence that an 8.4 s hole erases the history. Provenance, reference, channel type, restart-hole retention, index placement, and the restart caption are corrected in `docs/work/completed/WORK-2026-11-17-waveform-viewer-review-remediation.md`.

## Human Review

The project owner approved the plan and ADR-0012 by requesting implementation on 2026-11-17. ADR status is Accepted on that basis.
