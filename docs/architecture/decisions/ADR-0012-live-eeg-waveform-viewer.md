# ADR-0012: Live EEG waveform viewer

- Status: Accepted
- Date: 2026-11-17
- Decision Owner: Project owner (accepted by approving the implementation plan on 2026-11-17)
- Related Work: `docs/work/completed/WORK-2026-11-17-live-eeg-waveform-viewer.md`
- Supersedes: None

## Context

Verified on `main` at `43c0f38`:

- The engine lifespan owns a deterministic synthetic adapter: 16 EEG channels, 125 Hz, 25-sample blocks, unit `uV`, reference `synthetic`, labels `Fp1, Fp2, F3, F4, F7, F8, C3, C4, Cz, P3, P4, T7, T8, O1, O2, Pz`. Seed and block size are the only environment overrides. Output is labeled synthetic.
- Protocol v2 on `WS /ws/v2/eeg` sends `stream.metadata`, `eeg.block`, and `stream.status`. Samples are channel-major. Sample time is `firstSampleTimeUs + i * 1e6 / nominalSampleRateHz` on an engine-monotonic microsecond clock. A new session uses a new `streamId`. Restarting the process resets that clock.
- `EegStreamClient` validates messages, tracks integrity, and reconnects with jittered backoff from 500 ms to 10 s. Accepted samples are delivered only through `onBlock`. React receives throttled status snapshots with no samples. `StreamStatusPanel` shows connection, provenance, channel count, and rate. No waveform buffer or plot existed (`docs/architecture/OVERVIEW.md`).
- ADR-0008 decision 10 reserved `onBlock` for this buffer and kept samples out of React state. ADR-0006 keeps rendering off the acquisition path. This ADR extends those decisions with the viewer behavior. It does not change the wire contract.

## Decision

1. **Desktop only.** Plot the existing simulated stream. Do not change the schema, the WebSocket path, the client reconnect policy, or the synthetic generator.
2. **Buffer.** A `WaveformBuffer` subscribes to `onBlock` and stores `ceil(nominalSampleRateHz * 10)` samples per channel in ring buffers. At 125 Hz that is 1250 samples. The viewer refuses a stream above 64 channels or 20 000 samples per channel instead of truncating it.
3. **Time axis.** Slots are one nominal sample apart, using the stream rate and channel order from metadata. Within one `streamId`, an index jump or `droppedSamplesBefore` inserts that many empty slots. A new `streamId`, or a backwards `firstSampleTimeUs` (more than half a sample, so rounding is not a restart), starts a new clock domain: previous samples stay when the layout and rate match, and the hole width is the client-observed silence, at least 250 ms and at most 10 s. Reset monotonic timestamps are never subtracted from the previous process clock. A layout or rate change clears the buffer.
4. **Paint.** A canvas draws stacked, labeled lanes at `requestAnimationFrame`. Empty slots break the polyline. Each lane uses a fixed ±100 µV scale. Status text continues to come from the throttled snapshot. The figure states that a synthetic stream is not a measurement.
5. **While disconnected.** The traces freeze on the last accepted sample. The hole is written when the next accepted block arrives.

## Alternatives Considered

- Add uPlot, D3, or Plotly. Rejected for this PR: 16 polylines do not need a new dependency, and a chart library would encourage putting series data into React state.
- Store blocks in React state and render SVG on each message. Rejected: blocks arrive every 200 ms and would rerender the page, including the anatomy viewer, and an unbounded list would grow without a cap.
- Place every sample by absolute `firstSampleTimeUs` on one axis. Rejected: an engine restart resets the monotonic clock, so new samples would land far to the left of the old window or draw backward across the outage.
- Advance the axis with wall-clock empty slots during the disconnect. Rejected: the axis would contain time the stream did not measure. Freezing, then inserting the observed hole on resume, keeps the axis in nominal sample spacing.
- Change the simulator to emit a new frame type. Rejected: it already emits 16 labeled `uV` channels.

## Consequences

- The plotted clock matches nominal sample spacing inside one stream. Across an engine restart it is a display timeline joined by an observed hole, not one continuous monotonic clock. The caption says when a new `streamId` caused that hole.
- The 250 ms floor applies only to a new clock domain, so a sub-second restart is still visible at 125 Hz. In-stream gaps keep their true sample count and can be narrower than a pixel.
- ±100 µV will clip a later device stream with larger amplitudes. Stored samples are unchanged. A physical-device scale needs its own decision.
- The buffer is a live view. It is not a recording, and a slow consumer can still lose blocks in the engine’s live-view queue. Those losses appear as index gaps and breaks.
- Canvas 2D adds no package and no network. Worst-case allocation for an accepted stream is 64 × 20 000 float64 values, about 10 MB.

## Validation and Rollback

Unit tests cover channel order, ring rollover, in-stream gaps, and a new `streamId` with a reset `firstSampleTimeUs`. A component test checks labels, connection text, and that a gap starts a new stroke. `yarn nx run-many -t lint test typecheck build` and the governance checks cover the rest. The manual check is engine plus desktop: 16 scrolling labels, stop the engine, start it, see a hole and then new traces with no line across the hole.

Rollback is reverting this desktop view, the buffer, and the overview sentence. The WebSocket contract and acquisition process stay as they are.

## Post-acceptance correction

ADR-0013 corrects viewer behavior this decision left wrong or ambiguous. The desktop-only viewer, nominal spacing, ±100 µV lanes, and the same-id half-sample clock rule stay.

- Provenance kind, electrical reference, and channel type are part of layout identity. A change clears the rings, so a synthetic caption cannot describe device samples.
- In-stream empty slots follow the sample-index gap. `droppedSamplesBefore` does not add further slots when it disagrees with that gap.
- A restart hole stays visible when the next block is longer than the remaining window. The caption says "new stream" only for a new `streamId`. A same-id backwards clock has its own sentence. The sentence clears once that hole leaves the window.
- An isolated finite sample is drawn. The 8.4 s smoke note in the 03A work record, which said the rest of each lane was blank, overstates a full ring: a hole shorter than the window keeps older samples.

Recorded in `docs/work/completed/WORK-2026-11-17-waveform-viewer-review-remediation.md`.
