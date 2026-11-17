# ADR-0022: Milestone 04A review remediation

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner
- Related Work: `docs/work/completed/WORK-2026-11-17-milestone-04a-review-remediation.md`
- Supersedes: None. Corrects proposed ADR-0016 before acceptance. Leaves EEG protocol v2 unchanged.

## Context

An independent review of `04A/live-eeg-assistant` reproduced defects that the existing suite did not cover. The focused engine tests were green. Probes against the same code showed:

- `ReplayEegAdapter` kept the pre-gap sample index when the next present run started at the same stored offset, so a declared gap was published as contiguous samples.
- Pause only blocked the adapter loop. Block deadlines stayed on the original open time, so a monotonic clock that advanced during the pause made the rest of the file eligible to emit immediately.
- Baseline lock compared the recording's absolute sample index with 20 s. After a seek to the alpha finding at sample 2418, no windows were collected and `lock_baseline()` stayed false.
- Findings kept `quality: "good"` after a new stream, and an evidence click sought whatever recording was open.
- EDF import scaled every channel, including non-EEG, by 1e6 and the header called device provenance a live device measurement.
- `analysisSamplesExpired` did not count a normal 60 s rollover. Acquisition health was not connected to the analyzer. A session change did not cancel the llama HTTP call. Model answer text was returned once the cited ids existed. Session HTTP errors were ignored. The sample checksum did not cover rate, labels, reference, or gaps.
- The blink gate averaged O1 and O2, which cancels opposite polarity.

The approved plan still rejects windows missing more than 5% of their samples. That rule stays. Windows at or below 5% still need a numeric series for the periodogram.

## Decision

1. Recompute the timeline index from each present run. Pause duration is added to later deadlines.
2. Baseline collection and the first full window are measured from the current stream's first sample index. Explicit `lock_baseline` can lock whatever clean windows have been collected.
3. A new stream marks older findings `stale`. Typed and clicked seek require the finding's recording id to match the open recording. Stale findings from that recording remain seekable. Answers still cite only the current generation, and the sentence is built from stored measurements.
4. EDF import keeps EEG rows, converts volts to µV, and drops other channel types. Replay with device kind `replay` is labeled as file playback on the playback clock.
5. The history counter increments when a stored sample is replaced. The analyzer reads acquisition health before each accepted block. Generation change cancels the in-flight llama connection. `recording.v1` stores `manifestSha256` over the metadata, and channel indexes must match their positions.
6. A gap at or below 5% is replaced by the window mean only inside that spectral estimate. The finding keeps the accepted-sample fraction, and the template sentence says so. The occipital blink comparison uses the louder of O1 and O2.

ADR-0016, ADR-0017, and ADR-0018 stay Proposed until the owner marks them Accepted.

## Alternatives Considered

- Reject every window that contains any gap. Rejected: the approved plan allows a qualified finding when at most 5% of the window is missing. The mean substitution is now stated on the finding and in ADR-0016.
- Add a new EEG provenance kind for file replay. Rejected: protocol v2 stays unchanged. Device kind `replay` already distinguishes the file adapter.
- Leave model prose in place when the cited ids exist. Rejected: the ids would lend authority to a sentence the server did not check.

## Consequences

Gapped recordings seek and display on the declared indexes. Pause no longer fast-forwards. A seek into the last few seconds of a file can lock a baseline only after the user asks, because 20 s of new data are not available. Older findings remain visible and are marked stale. EDF stim channels are omitted. Manifests written before `manifestSha256` fail closed and must be rewritten. Mean substitution can still move a band-power estimate; the fraction and the sentence disclose it.

## Validation and Rollback

Gap replay, pause-versus-a-moving-clock, seek-then-lock, stale findings, manifest tamper, EDF channel selection, health gating, model-prose replacement, and cancel-on-session-change are covered by engine tests. Desktop tests cover the recording-id seek guard, the replay status sentence, and a rejected pause. Rollback is a revert of this remediation. ADR-0016's corrected sentences should be accepted or rejected with it.
