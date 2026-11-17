# WORK-2026-11-17-waveform-label-gutter: Shrink the waveform label column

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0021-waveform-label-gutter.md`

## Objective

Remove the unused left space in each EEG waveform row by sizing the channel-name column to the labels.

## Scope

In scope: `WaveformView` plot columns and channel-button padding.

Non-goals: the time axis, lane height, sample drawing, and the header.

## Acceptance Criteria

- [x] The label column is only as wide as the channel names, the selection bar, and a small gap before the trace.
- [x] Channel buttons still select a lane, and the pressed style still shows.
- [x] The trace uses the remaining width of the row.

## Implementation Summary

The plot’s first column is `max-content`. Channel buttons size to their text, with 8px on the left, the selection bar, and 8px before the trace. The first pass used no left padding; the owner asked for a little of that inset back.

## Validation Evidence

- `yarn nx run desktop:test -- src/stream/WaveformView.spec.tsx src/app/app.spec.tsx` — 10 passed.
- Browser at `http://127.0.0.1:4200` with live samples: the first pass measured the Fp1 label at 28px. After restoring 8px on each side of the name, the label measured 38px and the canvas 896px, still well under the old 72px column.

## Risks and Follow-ups

The owner accepted ADR-0021 on 2026-11-17. A longer channel name widens this column.

## Human Review

The owner requested this on 2026-11-17 and accepted ADR-0021 on 2026-11-17.
