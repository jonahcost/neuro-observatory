# ADR-0013: Waveform viewer review remediation

- Status: Accepted
- Date: 2026-11-17
- Decision Owner: Project owner (authorized applying the justified Milestone 03A review fixes on 2026-11-17)
- Related Work: `docs/work/completed/WORK-2026-11-17-waveform-viewer-review-remediation.md`
- Supersedes: None (clarifies ADR-0012; the live-viewer decision stands)

## Context

ADR-0012 added a desktop `WaveformBuffer` and canvas `WaveformView` for the existing protocol v2 stream. An independent review compared that staged implementation with the decision, the completed work record, and the scientific-integrity rules. Re-reading the code confirmed these defects:

- `synthetic` is stored only when the rings are allocated. A later stream with the same labels, units, and rate keeps the old flag, so device samples can be captioned as generated, and synthetic samples can lose that sentence. Reference and channel type are also ignored, so electrically different samples stay on the same trace.
- A new clock domain inserts a hole and then appends the whole next block. A block at least as long as the window overwrites the hole in the same call. `block_size` is a supported override up to 10000 samples, and the schema allows that size.
- Inside one stream, empty slots use `max(indexGap, droppedSamplesBefore)`. The sample index is the position of the values. A larger `droppedSamplesBefore` on an index-contiguous block, which the integrity tracker still accepts, invents time and shifts the trace. The current engine sets the two fields equal, so the synthetic adapter does not emit this.
- The restart caption always says "new stream". ADR-0012's consequence says that sentence is for a new `streamId`. A same-id backwards `firstSampleTimeUs` is a separate accepted clock-domain rule.
- A finite run of one sample is `moveTo` plus `stroke` and no `lineTo`, so Canvas 2D draws nothing.
- A negative index gap inserts one empty slot and then appends the overlapping samples again. `EegStreamClient` does not deliver those blocks; the buffer API still duplicates them.

The same-id half-sample clock rule in ADR-0012 decision 3 stays. It is the accepted way to avoid treating timestamp rounding as a restart, and the synthetic nominal clock does not step backwards. Changing it would reverse that decision. The 64 × 20000 paint cost is a follow-up, not a defect in the 16 × 125 Hz stream.

The completed 03A smoke note said an 8.4 s outage left only the newest block. A full 1250-sample ring keeps older samples until the observed hole reaches the window.

## Decision

1. **Layout identity** includes channel labels, units, channel types, electrical references, nominal rate, and provenance kind. A change clears the rings and sets the synthetic sentence from the new metadata. A new `streamId` with the same identity still keeps prior samples and inserts the observed hole.
2. **Restart hole.** After a clock-domain break, retain `min(gap, capacity - 1)` empty slots when the window can hold a slot and a sample, and keep only the newest samples that fit after those slots. The hole is not overwritten by the block that follows it.
3. **In-stream placement follows the sample index.** Insert `max(0, firstSampleIndex - nextSampleIndex)` empty slots. Ignore `droppedSamplesBefore` for placement when it disagrees with that gap. If `firstSampleIndex` is behind `nextSampleIndex` and the timestamp did not start a new clock domain, append only the samples at or after `nextSampleIndex`. Ignore a block that is entirely behind that index.
4. **Caption.** "New stream" is used only when `streamId` changes. A same-id backwards clock gets its own sentence. Either sentence clears once later slots have pushed that hole out of the window.
5. **Single-sample runs** draw a one-pixel segment so an isolated sample is visible.
6. **Unchanged.** No protocol, engine, client reconnect, scale, or dependency change. The ±100 µV lanes and the same-id half-sample clock rule remain ADR-0012.

## Alternatives Considered

- Leave the defects documented and ship ADR-0012 unchanged. Rejected: the synthetic sentence is a measurement claim, and a supported block size can erase the restart hole the decision requires.
- Break the clock domain only on `streamId` and ignore a same-id backwards timestamp. Rejected for this chunk: ADR-0012 accepted that rule so rounding is not a restart. The caption is corrected instead.
- Insert `droppedSamplesBefore` slots even when the index is contiguous. Rejected: those slots are time the sample index does not contain, and the engine already derives that field from the index gap.

## Consequences

A synthetic stream followed by a same-montage device stream starts a new plot and drops the synthetic sentence. A reference or channel-type change does the same. Restart holes remain visible when the next block is long, by showing that block's tail rather than its prefix. Inconsistent `droppedSamplesBefore` no longer shifts the trace. The same-id backwards-clock caption no longer claims a new stream. A one-sample run is a short stroke.

A device clock that steps backwards by more than half a sample on the same `streamId` still opens a clock domain of at least 250 ms. That remains the ADR-0012 rule. Painting every sample at the 64 × 20000 cap can still be heavy on the main thread. The viewer is still not a recording.

## Validation and Rollback

Buffer tests cover provenance, reference, and channel-type changes; a window-sized restart block; an index-contiguous block with a larger `droppedSamplesBefore`; an overlapping resend with a forward timestamp; and caption clearance. A view test covers the two caption sentences and a one-sample stroke. Rollback is reverting this remediation. ADR-0012's viewer remains the behavior to restore.
