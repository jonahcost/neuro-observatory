# WORK-2026-11-17-assistant-benchmark: Analyzer timing on this Mac

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0016-live-eeg-replay-and-findings.md`, `docs/architecture/decisions/ADR-0017-local-llama-assistant.md`

## Objective

Record measured analyzer timing and memory for the 16-channel alpha-step recording, and state which assistant targets were not measured.

## Scope

In scope: `python -m neuro_engine.assistant.benchmark` on the local machine, using `VirtualClock` so the 26 s recording does not wait in real time.

Non-goals: downloading a GGUF, measuring llama-server time to first token, and measuring browser `requestAnimationFrame` interval.

## Acceptance Criteria

- [x] Cold analysis of the alpha-step recording finished and reported a finding count.
- [x] Warm periodogram time and process RSS were measured.
- [x] Model time to first token and renderer frame interval are recorded as not measured.

## Implementation Summary

The script feeds the alpha-step samples through `BandPowerAnalyzer`, times one cold pass and five warm periodograms, and reads `ru_maxrss`. It does not spawn llama-server.

## Validation Evidence

Command: `cd services/neuro-engine && uv run python -m neuro_engine.assistant.benchmark`

Measured result:

- coldAnalyzerSeconds: 0.021814291998452973
- coldFindings: 2
- warmPeriodogramSecondsP95: 1.6832998881000094e-05
- warmPeriodogramRepeats: 5
- rssBytes: 44515328
- model: unavailable
- modelNote: llama-server weights were not installed; time to first token was not measured.
- rendererNote: requestAnimationFrame interval was not measured from this process.

The cold analyzer time is under the 0.05 s analysis-step target. RSS is under the 4_000_000_000 byte target. The 1.5 s time-to-first-token target and the 0.034 s frame-interval target were not measured.

## Risks and Follow-ups

These numbers are one local run, not a statistical benchmark and not a browser frame trace. A later run with weights installed has to measure time to first token before any GPU-layer default changes.

## Human Review

The owner directed implementation of the 04A plan on 2026-11-17 and accepted ADR-0016 and ADR-0017 on 2026-11-17. Time to first token and the renderer frame interval remain unmeasured.
