# ADR-0021: Tighten waveform channel labels

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner (requested 2026-11-17; this record stays Proposed until the owner marks it Accepted)
- Related Work: `docs/work/completed/WORK-2026-11-17-waveform-label-gutter.md`
- Supersedes: None. The 10 s window, ±100 µV scale, and lane order from ADR-0012 and ADR-0015 stay.

## Context

The EEG Waveforms plot reserves 4.5rem for channel names. Those names are two or three characters, right-aligned, so each row has an empty strip on the left of the label before the trace.

## Decision

The label column sizes to the channel names. Each name keeps 8px on its left and 8px before the trace, plus the selection bar. The trace still uses the rest of the row.

## Alternatives Considered

- Keep the 4.5rem column. Rejected: the owner asked to remove the unused left space.
- Drop the names and draw them on the canvas. Rejected: the names are the channel buttons.

## Consequences

The traces gain the width the fixed column was wasting. A longer future label widens the column instead of overflowing.

## Validation and Rollback

Measure the label column against the canvas in the desktop. Restoring `grid-template-columns: 4.5rem minmax(0, 1fr)` returns the previous gutter.
