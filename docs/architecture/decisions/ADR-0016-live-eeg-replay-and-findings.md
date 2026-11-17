# ADR-0016: Replay recordings and local EEG findings

- Status: Accepted
- Date: 2026-11-17
- Decision Owner: Project owner (directed on 2026-11-17; accepted on 2026-11-17)
- Related Work: `docs/work/completed/WORK-2026-11-17-live-eeg-replay-and-findings.md`
- Supersedes: None. Leaves EEG protocol v2 and anatomy v1 unchanged.

## Context

Verified on `04A/live-eeg-assistant` at `ffcb296`:

- The only EEG source is `SyntheticEegAdapter`. `EngineSettings.device` accepts only `synthetic`. `DeviceAdapter` is single-use (`open`, `blocks`, `close`) and has no seek method.
- `WS /ws/v2/eeg` is server-to-client. A client message closes the socket with 1003. Samples are channel-major µV on an engine-monotonic clock. There is no quality, marker, or command field.
- The desktop keeps a 10 s `WaveformBuffer` and a 1 s RMS electrode highlight. There is no playback control, command bus, or assistant.
- ADR-0004 requires replay to enter the same adapter abstraction as live data. No recording format exists. Real EDF, BDF, and FIF files stay outside Git.

## Decision

1. **EEG v2 stays one-way.** Findings, session control, and commands are a new loopback contract, `assistant.v1`, under `/api/assistant/v1`. They are not added to `eeg.block`.
2. **`recording.v1` is a local directory.** `manifest.json` plus little-endian float64 `samples.f64` in channel-major order, with declared gap ranges. The desktop does not read the file. Replay samples are not committed.
3. **`ReplayEegAdapter` implements `DeviceAdapter`.** Seek and source changes stop the current adapter and open a new one, which already issues a new `streamId`. Pause adds the time spent paused to later block deadlines, so resume continues at the next sample instead of catching up to the wall clock. Declared gap indexes are emitted as index holes. The default lifespan source remains the existing synthetic adapter, and its config hash is unchanged.
4. **Analysis taps accepted blocks inside the engine** after gap accounting, not the live-view WebSocket. A 60 s history drops the oldest raw samples and counts them. It does not invent samples. Windows are 2.0 s with a 0.5 s step. Narrated bands are theta 4–8 Hz, alpha 8–13 Hz, and beta 13–30 Hz, in µV², compared with the median baseline in dB. The baseline locks after 20 s of accepted windows or an explicit lock. A new stream clears it unless the caller passes keep-baseline.
5. **A finding stores summaries, not raw samples:** identity, sample-index range, monotonic times, channel labels, reference, method version, powers, baseline, dB change, and quality. The store keeps the latest 200 findings or 30 minutes. A new stream marks older findings `stale`. Answers may cite only ids from the current generation. Seek of a stale finding is allowed only when its recording id is the open recording.
6. **Commands are a closed lexicon** validated against the current montage and display modes: emphasize the posterior labels that are present (`O1`, `O2`, `Pz`, `P3`, `P4`), seek a finding only when the open recording still contains it, add a derived marker, lock the baseline, or set a display mode. Ambiguous or stale requests change nothing.

## Alternatives Considered

- Stuff findings into protocol v2. Rejected: a client message already closes the socket, and a breaking change needs a new EEG schema version.
- Seek by rewinding one adapter instance. Rejected: adapters are single-use and continuity is not assumed across a clock jump.
- Analyze the desktop 10 s ring. Rejected: the live-view queue can drop blocks, and raw samples must not become the assistant's memory.
- Pause live synthetic acquisition. Rejected: acquisition stays independent of the UI.

## Consequences

Replay and templates work without a language model. Seek starts a new stream, so in-flight answers from the old generation are discarded. Spectral estimates are scalp measurements in the declared reference, not cortical source estimates. Replay keeps declared gap indexes as holes. A window missing more than 5% of its samples produces no qualified finding. A smaller hole is replaced by the mean of the finite samples only inside that spectral estimate, and the finding records the accepted-sample fraction. Imported EDF files keep their EEG labels, omit non-EEG channels, and are shown as file replay. Engine timestamps for those files are the playback clock. The review corrections are in `docs/architecture/decisions/ADR-0022-milestone-04a-review-remediation.md`, accepted with this record on 2026-11-17.

## Validation and Rollback

Replay of the deterministic alpha-step fixture matches the file sample for sample. The occipital step produces an alpha finding whose channels include `O1` and `O2` and whose change is at least 3 dB. A flat fixture produces no qualified finding. Removing the assistant routes, the replay adapter, and the analyzer returns the process to the synthetic lifespan. Recorded files under the data directory can be deleted without touching the synthetic default.
