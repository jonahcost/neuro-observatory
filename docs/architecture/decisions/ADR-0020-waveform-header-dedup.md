# ADR-0020: Waveform card omits header status text

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner (requested 2026-11-17; this record stays Proposed until the owner marks it Accepted)
- Related Work: `docs/work/completed/WORK-2026-11-17-waveform-header-dedup.md`
- Supersedes: The waveform-figure copies of the connection, health, and synthetic-provenance sentences in ADR-0013 and ADR-0015. Restart captions stay on the waveform.

## Context

The header already shows connection, health, and the synthetic or device provenance sentence. The EEG Waveforms card repeats “Connected · Live” and “Synthetic signal — generated, not measured from a person.” The owner asked for those repeats to be removed.

## Decision

The waveform card does not repeat connection, health, or the synthetic-provenance sentence. Those stay in the header. A clock-restart caption still appears on the waveform, outside Trace notes, because the header does not describe that gap.

## Alternatives Considered

- Keep both copies. Rejected: the owner asked to remove the duplicate lines.
- Also remove the restart caption. Rejected: that caption is about the trace, and the header does not show it.

## Consequences

A viewer who looks only at the waveform card no longer sees connection or provenance there. The header remains on screen with the shell. Protocol, acquisition, and the waveform buffer are unchanged.

## Validation and Rollback

Desktop tests expect the waveform region to omit those two sentences and still show a restart caption. Restoring the two paragraphs in `WaveformView` returns the previous copy.
