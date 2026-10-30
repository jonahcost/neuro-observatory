# ADR-0009: Milestone 01A review fixes: acquisition boundary hardening

- Status: Accepted
- Date: 2026-10-30
- Decision Owner: Project owner (accepted explicitly in chat on 2026-10-30 after reviewing the verification results)
- Related Work: `docs/work/completed/WORK-2026-10-30-acquisition-boundary-hardening.md`
- Supersedes: None (narrowly extends and corrects ADR-0008)

## Context

An independent review of the Milestone 01A change set (commit `a43fbeb`, ADR-0008) reproduced these defects with probes against the real code. None of them is reachable with the shipped synthetic adapter, but each one breaks the device-independent contract that ADR-0008 establishes:

- **Close failure masks the cause.** `AcquisitionService._run_stream` awaits `adapter.close()` in `finally` before publishing `StreamClosed`. Probe: an adapter raising the retryable `DeviceDisconnectedError` and then failing in `close()` ended in `failed` with `internal-error`. There was no reconnect, `current_stream` still pointed at the dead stream, and `StreamClosed` was never published. The same exception escapes `stop()`.
- **Protocol limits enforced only at the per-client edge.** `StreamDescriptor` and `_accept` do not check schema limits (device-kind pattern, text lengths, channel count, rate, `sampleCount <= 10000`, time range). Pydantic first rejects them inside each WebSocket session, and `_send_stream` does not handle those errors. Probe: device kind `"OpenBCI"` made every WebSocket fail with an unhandled `ExceptionGroup` and `/api/v2/stream` return 500, while `/health` said `ok`. A 12 000-sample block crashed every client session. This contradicts ADR-0008 decision 5.
- **Health says `ok` without data.** `/health` reports `degraded` only for `failed`. Probe: NaN on one channel of every block gave 102 rejected blocks, 0 samples acquired and `/health` `ok`/`streaming`.
- **Sample-index contract.** The `SampleBlock` docstring says `first_sample_index` "comes from the device's own counter", but the service assumes a per-stream index starting at 0 and never wrapping. Probe: a counter starting at 1 000 000 produced a 1 000 000-sample declared gap and an effective rate of 772 108 Hz, because the rate uses the absolute index since stream open.
- **Parity (ADR-0008 decision 1).** Integral floats such as `firstSampleIndex: 10.0` are valid under the canonical schema (`jsonschema`) and Ajv, but Pydantic strict mode rejects them as `schema`. A literal `NaN` is a `json` error in TypeScript but `semantic` in Python, because `json.loads` accepts `NaN`/`Infinity`.
- **Threading.** `/health` and `/api/v2/stream` are sync `def` handlers, so FastAPI runs them in a worker thread that reads loop-owned state (`status()` dereferences `self._stream` twice).
- **Metadata ordering.** The schema and READMEs say metadata is "sent first on every connection". When no stream is open, the server sends status first. The WebSocket also reads `current_stream` after scheduling its tasks rather than at subscription time, which leaves a small window for blocks without metadata context.
- **Desktop.** A throwing `onBlock` listener aborts delivery to later listeners and skips the snapshot update.

Constraints: ADR-0002, ADR-0004 and ADR-0008. Raw samples are never fabricated or altered. Protocol v2 stays structurally unchanged; no new dependencies, ports or services.

## Decision

Owner decisions (chat, 2026-10-30): fix all of the items above; split oversized blocks; use the full health rule; defer the NaN policy; record the change in this new ADR.

1. **Close isolation.** Adapter `close()` errors are logged and never replace the session's original outcome. `StreamClosed` is always published and `current_stream` is always cleared, including on cancellation. `stop()` never raises because of `close()`.
2. **Validate at the acquisition boundary.** `DeviceInfo`, `ChannelSpec`, `SyntheticProvenance` and `StreamDescriptor` enforce the protocol v2 limits at construction and raise the non-retryable `DeviceConfigError`. The limits are defined once in `acquisition/base.py`, and a test asserts they equal the canonical schema values. `_accept` also rejects (and counts) blocks whose sample-index range or timestamps fall outside the protocol's integer range.
3. **Split oversized blocks.** A valid adapter block with more than 10 000 samples is published as consecutive blocks of at most 10 000 samples. Each part gets its own `blockSequence`. Only the first part carries `droppedSamplesBefore`. The *k*-th part's `firstSampleTimeUs` is `first + round(offset * 1e6 / nominalSampleRateHz)`, which is the protocol's own sample-time rule, and raw device timestamps are sliced to match. No sample values change.
4. **Deliberate WebSocket failure.** If a message cannot be encoded, the session logs the error and closes with 1011 (internal error). `_send_stream` no longer treats every `RuntimeError` as a client disconnect; only disconnect errors are mapped to "client left".
5. **Health rule.** `/health` reports `degraded` with `degradedReasons` when any of these holds:
   - `not-streaming`: the state is not `streaming`.
   - `no-recent-data`: no block was accepted within the stale window. The window is 3 durations of the last accepted block and at least 1 s, measured from the last accepted block or from stream open.
   - `recent-rejections`: a block was rejected within that window.

   `/health` also reports counters (`samplesAcquired`, `acquisitionGapSamples`, `rejectedBlocks`, `effectiveSampleRateHz`). Its shape is local diagnostics, not part of protocol v2.
6. **Sample-index contract and rate.** The adapter contract is documented as follows: `first_sample_index` is a per-`open()` counter that starts at 0 for the first sample acquired after `open()`, never wraps and is rebased by the adapter. If an adapter cannot determine a gap's length (for example after a hardware counter wraps during an outage), it raises `DeviceDisconnectedError` so the service opens a new stream instead of declaring a guessed gap. `effectiveSampleRateHz` becomes the sample-index advance per second of engine time between the first and the latest accepted block, gaps included, and is `null` until that span is at least 1 s. This removes the dependence on index origin and first-block latency. Only the schema description changes; the field stays a non-negative number or `null`. The only consumer is the desktop status panel, so `schemaVersion` stays 2.
7. **Parity.** Python accepts integral floats for integer fields (`Counter`, `sampleCount`), as the canonical schema does. Booleans and non-integral values are still rejected. Python JSON decoding rejects `NaN`/`Infinity`/`-Infinity` as `json` errors, as `JSON.parse` does. New shared fixtures cover both cases.
8. **Async HTTP handlers.** `/health` and `/api/v2/stream` become `async def` and run on the event loop that owns acquisition state.
9. **Metadata ordering.** The WebSocket reads `current_stream` in the same synchronous step as `subscribe()`. Documentation states that metadata is sent first *when a stream is open*; otherwise status comes first and metadata follows when a stream opens.
10. **Desktop listener isolation.** Each `onBlock` listener is called inside its own `try/catch`. Failures are counted in `EegStreamSnapshot.listenerErrors`, logged with `console.error` and shown in the status panel. They are never swallowed silently.
11. **Deferred (owner decision).** One non-finite value still rejects the whole block. The per-channel validity policy is decided in the 01B protocol v3 ADR.

Corrections to ADR-0008, recorded here instead of rewriting its accepted substance:
- Decision 1's claim that both languages classify fixtures identically held only for the existing fixtures. Item 7 above restores it.
- Decision 5's claim that the service rejects malformed adapter output did not cover protocol limits. Items 2 and 3 above restore it.
- The 01A work record's "not committed / CI not run" statements became stale after commit `a43fbeb` and [PR #8](https://github.com/jonahcost/neuro-observatory/pull/8). A dated correction note is added to that record.

## Alternatives Considered

- **Oversized blocks:** reject and count them, so the lost samples appear as a declared gap. This loses valid data the adapter already delivered.
- **Boundary validation:** build the Pydantic metadata message at `open()` and map its errors to `DeviceConfigError`. This avoids duplicating the limits but makes acquisition import the protocol layer, which already imports acquisition and would create a cycle. Another option is to keep validation only at the WebSocket edge. That is the current behavior and it fails per client, while health stays green.
- **Health:** report `degraded` only on failure plus a stall, or keep the current rule and only add counters. Both hide rejected-data and reconnect periods.
- **Effective rate:** keep the rate since stream open and rely only on documentation. A contract violation would still produce a nonsensical rate.
- **Parity:** declare the divergence instead of fixing it. JSON cannot distinguish `10` from `10.0` in JavaScript, so tightening the schema is not possible.
- **Retain the current approach:** rejected, because each item above was reproduced.

## Consequences

- Benefits: adapter failures resolve to the correct state, and reconnects happen. Invalid descriptors fail fast with a clear, non-retryable error instead of breaking every client. Oversized device reads are delivered without loss. Health reflects whether data is actually flowing. Fixture parity is restored.
- Costs: the protocol limits now live in three places (schema, Pydantic and acquisition constants), guarded by a test. `/health` is briefly `degraded` (`not-streaming`) during startup and after a disconnect, which is accurate. `effectiveSampleRateHz` stays `null` for about 1.2 s instead of about 1 s.
- Scientific: no sample values or timestamps are changed apart from the split rule in item 3, which follows the protocol's existing sample-time definition. Whole-block rejection on NaN remains a known data-loss policy (item 11).
- Security and privacy: no new ports, egress or dependencies. Error logs name codes and locations, never sample values.

## Validation and Rollback

Validation: new engine tests for close failures (cause preserved, reconnect, `StreamClosed`, `stop()` safe), limit parity with the schema, descriptor rejection, block splitting (sequence, indices, times, gaps, identical data), out-of-range rejection, every health reason, a rate that does not depend on index origin, a WebSocket 1011 on encode failure, and status-first ordering without a stream. Shared fixtures for integral floats and literal `NaN` run in both languages. A desktop test covers listener isolation. `yarn nx run-many -t lint test typecheck build`, `check-generated` and the governance checks must pass, and the review probes are rerun.

Rollback: revert this change set as a unit. Protocol v2 is structurally unchanged, so ADR-0008 behavior returns without migration.
