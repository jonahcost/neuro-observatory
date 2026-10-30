# @neuro-observatory/protocol

Language-neutral contract between the Neuro Engine (producer) and its clients. Decision record: [ADR-0008](../../docs/architecture/decisions/ADR-0008-eeg-acquisition-protocol-foundation.md).

## Source of truth

| Artifact | Role |
| --- | --- |
| `schemas/eeg-stream.v2.schema.json` | Canonical JSON Schema (draft 2020-12). Edit this first. |
| `src/generated/eeg-stream.v2.ts` | TypeScript types generated from the schema. Never edit by hand. |
| `src/validate.ts` | Ajv validation + semantic checks; `parseServerMessage()` |
| `src/integrity.ts` | `StreamIntegrityTracker` (gaps, drops, duplicates, ordering) |
| `fixtures/v2/` | Valid/invalid messages and integrity scenarios shared with Python |
| `services/neuro-engine/src/neuro_engine/protocol/` | Pydantic mirror, semantic checks and integrity tracker (Python) |

Both languages run every fixture in `fixtures/v2/manifest.json` and every scenario in `fixtures/v2/integrity/` and must produce identical outcomes.

## Messages (server → client only)

Every message has `type`, `schemaVersion: 2` and `streamId`. Unknown fields are rejected.

- **`stream.metadata`** — sent first on every connection and whenever a new stream starts. Device, provenance (`synthetic` with generator/seed/config hash, or `device`), `nominalSampleRateHz`, ordered `channels` (`index`, `label`, `type`, `unit`, `reference`), `layout: "channel-major"`, and `timebase`.
- **`eeg.block`** — `samples[channel][sample]` in µV (`unit: "uV"`), float64 without rounding, in metadata channel order. `firstSampleIndex` counts samples since the stream started; `blockSequence` counts blocks; `droppedSamplesBefore` declares samples the device/engine lost immediately before this block. Missing samples are never fabricated.
- **`stream.status`** — acquisition state (`idle|connecting|streaming|reconnecting|stopped|failed`), counters and last error. `blocksDroppedForClient` counts blocks the engine dropped for *this* connection because it fell behind.

Client → server messages are not part of v2; the engine closes the socket with code 1003 if it receives one.

## Time

- All engine times are **engine-monotonic microseconds** (integers, JSON-safe).
- `timebase.anchor` pairs `monotonicUs` with `unixTimeUs`, captured once at stream open, for converting to wall-clock time.
- Sample *i* of a block is at `firstSampleTimeUs + i × 1e6 / nominalSampleRateHz` (see `sampleTimeUs()`).
- `timebase.timestampSource` states what the times mean: `synthetic-nominal` (exact by construction), `host-receipt-fitted` or `device-clock` (reserved for physical devices). Transmission or receipt time is never presented as acquisition time.

## Validation layers and error kinds

`parseServerMessage(raw, { metadata })` returns `{ ok: true, message }` or `{ ok: false, error: { kind, detail } }`:

| Kind | Meaning |
| --- | --- |
| `json` | Not parseable JSON text |
| `unsupported-version` | A numeric `schemaVersion` other than 2 |
| `schema` | Violates the JSON Schema |
| `semantic` | Schema-valid but inconsistent: channel indices ≠ positions, duplicate labels, row count ≠ channel count, row length ≠ `sampleCount`, non-finite values, or `streamId` ≠ current metadata |

Error details name the location and rule but never echo sample values.

## Changing the contract

1. Any incompatible change requires a new ADR and a new schema version (new file, new `schemaVersion`, new endpoint path).
2. Edit the schema, then regenerate types: `yarn nx run @neuro-observatory/protocol:generate-types`.
3. Update the Pydantic mirror in `services/neuro-engine/src/neuro_engine/protocol/v2.py`.
4. Add valid/invalid fixtures and register them in `fixtures/v2/manifest.json`.
5. Verify: `yarn nx run-many -p @neuro-observatory/protocol,neuro-engine,desktop -t test typecheck lint` and `yarn nx run @neuro-observatory/protocol:check-generated`.

`check-generated` (and `src/generated.spec.ts`) fail when the committed types drift from the schema.
