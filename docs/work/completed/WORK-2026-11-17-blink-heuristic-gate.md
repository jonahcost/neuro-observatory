# WORK-2026-11-17-blink-heuristic-gate: Frontal blink heuristic

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0018-blink-heuristic-gate.md`

## Objective

Detect a short frontal blink-shaped burst on Fp1 and Fp2 with an explicit heuristic, and keep the learned classifier unloaded.

## Scope

In scope: the Fp1/Fp2 duration, amplitude, correlation, and occipital-RMS gate; one finding per burst; `CLASSIFIER_ENABLED = False`.

Non-goals: training or loading a classifier, calling the result a diagnosis or a source estimate, and accepting ADR-0018 from synthetic evidence alone.

## Acceptance Criteria

- [x] A synthetic frontal burst emits one heuristic finding.
- [x] A burst that is too long, too occipital, or poorly correlated does not.
- [x] The assistant snapshot classifier field remains `disabled`.
- [x] Re-firing is suppressed for one second after a detection.

## Implementation Summary

`blink_verdict` checks the window before the band-power baseline early-return, so a burst in the first two seconds is still labeled. The sentence says it is a scalp artifact heuristic. `load_classifier` returns no model.

## Validation Evidence

- `cd services/neuro-engine && uv run pytest tests/test_blink.py -q --tb=line` — included in the focused run of 56 passed, and in the full run of 434 passed, 4 deselected.
- `cd services/neuro-engine && uv run ruff check .` — All checks passed.

## Risks and Follow-ups

The heuristic is not a held-out classifier comparison. A broadband burst can also emit a band-power finding. The owner accepted ADR-0018 on 2026-11-17 as the heuristic with the classifier disabled. A classifier still needs a later ADR. Blink findings still store the frontal peak in `rmsUv`.

## Human Review

The owner directed implementation of the 04A plan on 2026-11-17 and accepted ADR-0018 on 2026-11-17. A synthetic blink test is not acceptance of a classifier.
