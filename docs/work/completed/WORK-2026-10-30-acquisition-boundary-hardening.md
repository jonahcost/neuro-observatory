# WORK-2026-10-30-acquisition-boundary-hardening: Milestone 01A review fixes: acquisition boundary hardening

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0009-acquisition-boundary-hardening.md`

## Objective

Resolve the confirmed findings of the independent Milestone 01A review so that the device-independent acquisition boundary behaves correctly for any adapter, not only for the synthetic one.

## Scope

In scope:

- `services/neuro-engine`: `acquisition/base.py` (limits, contract docs), `acquisition/service.py` (close isolation, boundary checks, splitting, health, rate), `api/http.py` (async handlers, health), `api/ws.py` (subscribe-time snapshot, 1011 on encode failure), `protocol/v2.py` (integral floats, strict JSON decoding), tests.
- `packages/protocol`: schema descriptions (metadata ordering, rate definition), regenerated types, two new shared fixtures, README.
- `apps/desktop`: `onBlock` listener isolation, `listenerErrors` in the snapshot and panel.
- Docs: engine README, ADR-0009, and a dated correction note in the 01A work record.

Non-goals: per-channel NaN or validity policy (01B protocol v3 ADR), protocol v3 fields (units beyond µV, hardware metadata, clock fitting, unknown-length gaps), recorder, BrainFlow adapter, Python type checker, `ruff format` adoption, desktop reconnect-attempt reset without metadata.

Dependencies: owner decisions given in chat on 2026-10-30; ADR-0008 and the 01A branch (`a43fbeb`).

## Acceptance Criteria

Engine tests live under `services/neuro-engine/tests/`.

- [x] If an adapter's `close()` raises, the original error still drives the state (a retryable disconnect reconnects), `StreamClosed` is published, `current_stream` is cleared, and `stop()` does not raise. Tests: `test_acquisition_service.py::test_close_failure_keeps_the_retryable_cause_and_reconnects`, `::test_close_failure_after_a_disconnect_reports_the_disconnect`, `::test_stop_does_not_raise_when_close_fails`.
- [x] Descriptors that violate protocol limits fail as `DeviceConfigError` (`failed`, no retry). The limits equal the canonical schema values. Tests: `test_acquisition_limits.py` (schema parity, 19 rejection cases, values exactly at the limits accepted); `test_acquisition_service.py::test_descriptor_outside_protocol_limits_fails_without_retry`.
- [x] Blocks over 10 000 samples are split into contiguous protocol-sized blocks with identical data, consecutive sequences, the protocol time rule, and `droppedSamplesBefore` only on the first part. Out-of-range blocks are rejected and counted. Tests: `::test_oversized_blocks_are_split_into_contiguous_protocol_blocks`, `::test_blocks_outside_the_protocol_integer_range_are_rejected`.
- [x] A WebSocket encode failure closes the session with 1011. Without an open stream, the first message is status and metadata follows when a stream opens. Tests: `test_api.py::test_unencodable_message_closes_the_session_with_1011`, `::test_status_comes_first_when_no_stream_is_open_and_metadata_follows`.
- [x] `/health` reports `degraded` with `not-streaming`, `no-recent-data` or `recent-rejections`, and exposes counters. It reports `ok` while streaming normally. Tests: `test_health.py` (both tests); `test_acquisition_service.py::test_health_is_ok_while_streaming_and_reports_stalls`, `::test_health_reports_no_data_when_the_first_block_never_arrives`, `::test_health_reports_recent_rejections_until_the_window_passes`, `::test_health_is_degraded_while_reconnecting`.
- [x] `effectiveSampleRateHz` does not depend on the index origin. Tests: `::test_effective_rate_does_not_depend_on_the_index_origin` (exactly 125 Hz with indices from 1 000 000), `::test_effective_rate_is_unknown_until_one_second_of_blocks`.
- [x] Integral-float counters are valid and literal `NaN` is a `json` error in both TypeScript and Python. Shared fixtures `valid/block-integral-float-counters.json` and `invalid/block-nan-literal.txt` run in `validate.spec.ts` and `test_protocol_contract.py`.
- [x] A throwing `onBlock` listener does not stop other listeners and is counted in `listenerErrors`. Tests: `eegStreamClient.spec.ts` ("isolates onBlock listeners…"), `StreamStatusPanel.spec.tsx`.
- [x] `yarn nx run-many -t lint test typecheck build`, `check-generated`, the governance checks and the review probes pass. See Validation Evidence.

## Implementation Summary

- **`acquisition/base.py`:** protocol v2 limit constants. `__post_init__` validation on `ChannelSpec`, `DeviceInfo`, `SyntheticProvenance` and `StreamDescriptor` raises `DeviceConfigError`. The sample-index contract and `close()` behavior are documented on `SampleBlock` and `DeviceAdapter`.
- **`acquisition/service.py`:**
  - `close()` errors are logged in a nested `try/finally`, so `StreamClosed` and stream clearing always happen.
  - `_accept` rejects index or time values outside the protocol range and splits blocks over 10 000 samples (`_block_part`).
  - New `health()` / `AcquisitionHealth` with three reasons and a stale window of 3 block durations, at least 1 s.
  - The rate is measured between the first and the latest accepted block.
- **`api/http.py`:** `async def` handlers. `/health` gains `degradedReasons` and `acquisition.counters`.
- **`api/ws.py`:**
  - `current_stream` is read in the same synchronous step as `subscribe()`.
  - Protocol or validation errors close with 1011.
  - `RuntimeError` counts as a disconnect only when the socket is already disconnected.
- **`protocol/v2.py`:** `JsonInteger` before-validator (integral floats become `int`) on `Counter` and `sampleCount`; `decode_json` rejects `NaN`/`Infinity`.
- **`packages/protocol`:** schema descriptions for metadata ordering and the rate definition; regenerated types (doc comments only); two fixtures and their manifest entries; README.
- **`apps/desktop`:** `onBlock` listeners isolated with `try/catch`, `console.error` and an `EegStreamSnapshot.listenerErrors` counter, shown in the status panel.
- **Docs:** engine README (health, WebSocket codes, adapter contract); dated correction notes in ADR-0008 and the 01A work record.

## Validation Evidence

Commands were run on 2026-10-30 from the repository root on macOS with Python 3.12.16 and `NX_DAEMON=false`.

| Command | Result |
| --- | --- |
| `cd services/neuro-engine && uv run pytest -q` (before adding tests, after the source changes) | 139 passed (no regressions) |
| `yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache --output-style=static` | Passed for 3 projects. Protocol: 50 Vitest tests (was 48). Desktop: 15 Vitest tests (was 14). Engine: 180 pytest (was 139), ruff "All checks passed!". Same desktop chunk-size warning as before (more than 500 kB, mostly Three.js) and the same Starlette/httpx deprecation warning. |
| `yarn nx run @neuro-observatory/protocol:check-generated --skip-nx-cache` | "Generated protocol types are up to date." |
| New and changed engine tests run against the **original** source (`git archive HEAD services/neuro-engine/src` extracted to `/tmp`, put first on `PYTHONPATH`, with a test-local `MAX_SAFE_INTEGER` shim) | Every new behavioral test failed: close (3), limits (17 of 21; the 4 that passed cover rules the old code already enforced: no channels, zero rate, NaN rate, values exactly at the limits), descriptor, split, range, rate (2), health (4 service-level plus 2 API), 1011. The canonical-schema cases also failed there because the old code has no `decode_json`, which is expected collateral. The status-first test passed on both versions; it guards ordering. |
| Review probes rerun against the fixed code (`/tmp/fixed_probe.py`, `/tmp/parity_probe*.py`) | Close failure: kept `device-disconnected`, 8 opens / 8 `StreamClosed`, `stopped`, no stale stream. Device kind `"OpenBCI"`: `failed`/`invalid-device-config`, `/health` degraded `not-streaming`, `/api/v2/stream` 200, WebSockets receive status (previously 500 and `ExceptionGroup`). 12 000-sample blocks: delivered (previously session crash). NaN channel: degraded `recent-rejections` (previously `ok`). Counter from 1 000 000: rate 456 Hz, matching the probe's real output of about 500 Hz (previously 772 108 Hz). Parity: `10.0` valid in Python, literal `NaN` is `json`. |
| `uv run python /tmp/shutdown_probe.py` (real uvicorn on `127.0.0.1`, connected client, SIGINT) | Client saw close 1012 after 0.09 s; server exited with rc 0 after 0.27 s |
| `python3 -m unittest discover -s tools/governance/tests`; `python3 tools/governance/check_governance.py --all` | 5 tests OK; governance check passed |

Not run: GitHub Actions on this change (not committed or pushed); a browser run of the desktop against a live engine.

## Risks and Follow-ups

- Protocol limits are duplicated in acquisition constants (guarded by `test_limits_match_the_canonical_schema`).
- Whole-block NaN rejection remains; per-channel validity is deferred to the 01B protocol v3 ADR (owner decision).
- An adapter that violates the index contract (does not start at 0) still produces a declared gap equal to its offset. The rate is now correct, and the contract is documented.
- `/health` is `degraded` (`not-streaming`) briefly at startup and while reconnecting, by design.
- The Python test oracle (`jsonschema`) is weaker than Ajv and Pydantic for `pattern` with a trailing newline (documented in the protocol README).
- Still open from the review: protocol v3 expressiveness (units, hardware metadata, clock fitting, unknown-length gaps), lossless-overflow visibility in health, Python type checker, `ruff format`, tracked `.yarn/install-state.gz`.

## Human Review

Owner approved the scope and decisions in chat on 2026-10-30: all nine fixes, splitting oversized blocks, the full health rule, deferring the NaN policy, and a new ADR. After reviewing the verification results, the owner explicitly accepted ADR-0009 on 2026-10-30 (chat), and this record was then marked Completed and moved to `docs/work/completed/`. Nothing has been committed or pushed; the change still needs owner review in a PR and CI on GitHub.
