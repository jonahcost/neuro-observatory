# ADR-0018: Blink heuristic with the classifier disabled

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner (implementation of the attached 04A plan was directed on 2026-11-17; this record stays Proposed until the owner marks it Accepted)
- Related Work: `docs/work/completed/WORK-2026-11-17-blink-heuristic-gate.md`
- Supersedes: None.

## Context

ADR-0016 detects band-power changes. It does not label blinks. A small classifier would need blink-labeled sessions held out by subject. EEG Motor Movement/Imagery is not a blink corpus. No such labeled set is in this repository, and personal recordings must not be committed.

## Decision

1. Ship a versioned scalp heuristic, `blink-heuristic` method version `1`. It reports a likely blink only when `Fp1` and `Fp2` are both present, a shared high-amplitude burst lasts between 50 ms and 500 ms, the two frontal channels move together, and occipital RMS stays lower than the frontal burst. The finding is an artifact heuristic, not a source estimate and not a diagnosis.
2. If either frontal label is absent, the method stays off.
3. The classifier loader stays disabled. No weights are loaded and no classifier finding is emitted. Enabling a model requires a later ADR that records a held-out comparison: at most one false positive per minute on eyes-open rest, and precision at least 0.10 above this heuristic at that same cap.

## Alternatives Considered

- Train a logistic model on synthetic blinks and enable it. Rejected: synthetic injections can test the heuristic, but they are not held-out human sessions.
- Wait to ship any blink notice. Rejected: the heuristic is independently testable and the band-power assistant does not depend on it.

## Consequences

Users can see a blink notice on a montage that includes `Fp1` and `Fp2`. The notice can be wrong. The UI and the finding method name say it is a heuristic. A future classifier cannot turn on through a config flag alone.

## Validation and Rollback

Synthetic bursts cover a positive blink, a one-channel spike, a burst longer than 500 ms, and a burst that is also large on `O1`. `load_classifier` returns no model. Delete `analysis/blink.py` and its analyzer call to roll back.
