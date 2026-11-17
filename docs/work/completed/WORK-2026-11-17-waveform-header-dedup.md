# WORK-2026-11-17-waveform-header-dedup: Drop duplicate waveform status lines

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0020-waveform-header-dedup.md`

## Objective

Remove the connection, health, and synthetic-provenance lines from the EEG Waveforms card. Keep them in the header. Keep waveform restart captions.

## Scope

In scope: `WaveformView` and the desktop tests that assert those sentences.

Non-goals: header copy, stream details, waveform gap drawing, and the assistant.

## Acceptance Criteria

- [x] The waveform card does not show “Connected · Live” or the synthetic “not measured” sentence.
- [x] The header still shows connection, health, and provenance.
- [x] A clock restart caption still appears on the waveform, outside Trace notes.

## Implementation Summary

`WaveformView` no longer renders connection, health, or the synthetic sentence, and it no longer takes a stream snapshot. Restart captions stay on the card.

## Validation Evidence

- `yarn nx run-many -p desktop -t test lint typecheck` — all three targets passed.
- Browser at `http://127.0.0.1:4200` after the stream was live: the header text was “Synthetic EEG”, “Synthetic signal — generated, not measured from a person (seed 0)”, and “Connected · Live”. The waveform card text contained none of “Connected”, “Live”, or “Synthetic signal”.

## Risks and Follow-ups

The owner accepted ADR-0020 on 2026-11-17. The waveform card no longer states provenance on its own.

## Human Review

The owner requested this removal on 2026-11-17 and accepted ADR-0020 on 2026-11-17.
