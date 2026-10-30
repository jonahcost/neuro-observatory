# WORK-2026-10-30-eeg-acquisition-protocol-foundation: Milestone 01A: EEG acquisition and protocol foundation

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0008-eeg-acquisition-protocol-foundation.md`

## Objective

Replace the per-connection simulated WebSocket with a versioned, schema-validated EEG stream protocol (v2), a device-independent acquisition core owned by the engine lifecycle (deterministic synthetic adapter, monotonic timebase, sample-index integrity, bounded fan-out), and a validated desktop stream client.

## Scope

In scope:

- `packages/protocol`: JSON Schema v2, shared fixtures, Ajv validator + semantic checks, generated types, integrity tracker, test/typecheck targets.
- `services/neuro-engine`: acquisition interfaces, synthetic adapter, clocks, acquisition service, stream hub, Pydantic protocol mirror + Python integrity tracker, `/ws/v2/eeg`, `/health`, `/api/v2/stream`, settings.
- `apps/desktop`: validated stream client, status UI, removal of the unvalidated cast.
- `.github/workflows/ci.yml`: add `typecheck`.
- Docs: architecture overview, protocol README, engine README.

Non-goals: BrainFlow/OpenBCI adapter (01B), recorder and file format, replay adapter, waveform UI and sample ring buffer, DSP, signal quality/impedance, device control API, binary transport, multi-device synchronization, MRI, source localization, ML, holographic display.

Dependencies: owner approval of the plan (given 2026-10-30); governance baseline merged to `main` (`fdaf8ad`).

## Acceptance Criteria

Each criterion lists the tests that verify it (engine tests under `services/neuro-engine/tests/`, TS specs next to their sources).

- [x] Engine acquires continuously with zero clients; two clients receive identical `firstSampleIndex`/samples for the same block. — `test_api.py::test_acquisition_runs_without_any_client`, `::test_two_clients_receive_identical_samples`.
- [x] Same seed/config produces bit-identical synthetic output; spectral peaks at 10 Hz and 6 Hz; provenance `synthetic` end-to-end and visible in the UI. — `test_synthetic.py::test_same_seed_is_bit_identical_and_different_seed_differs`, `::test_adapter_output_equals_random_access_generation`, `::test_spectrum_peaks_at_configured_alpha_and_theta`; `StreamStatusPanel.spec.tsx` (synthetic vs device provenance label); smoke test metadata `provenance.kind = synthetic`.
- [x] Virtual-clock pacing has zero cumulative drift over 10 000 blocks; real-time effective rate within ±2 % of 125 Hz. — `test_clock.py::test_virtual_clock_pacing_has_no_cumulative_drift_over_10000_blocks` (exactly 2 000 000 000 µs), `::test_real_time_effective_rate_within_two_percent`; smoke test 124.8 samples/s received, engine-reported 124.98 Hz.
- [x] Every emitted message validates against the canonical schema; every invalid fixture is rejected with the expected error kind in both TS and Python. — `validate.spec.ts` and `test_protocol_contract.py` run all 32 manifest cases (6 valid, 26 invalid across `json`, `schema`, `unsupported-version`, `semantic`); `test_api.py::test_websocket_sends_metadata_first_then_valid_contiguous_blocks` and `::test_stream_endpoint_messages_match_the_canonical_schema` validate live engine output with `jsonschema`.
- [x] Gap, duplicate, out-of-order, transport-drop and stream-reset fixtures produce identical counters in TS and Python. — 7 shared scenarios in `fixtures/v2/integrity/`, run by `integrity.spec.ts` and `test_protocol_integrity.py`; desktop client path in `eegStreamClient.spec.ts` ("counts acquisition gaps, transport drops, duplicates and out-of-order blocks").
- [x] A slow client never delays acquisition; its drops are counted and reported; lossless overflow fails explicitly. — `test_acquisition_service.py::test_slow_consumer_does_not_delay_acquisition`; `test_hub.py::test_publish_is_synchronous_and_never_blocks_on_consumers`, `::test_live_view_drops_oldest_blocks_and_counts_them`, `::test_lossless_overflow_fails_explicitly_after_draining`.
- [x] Device lifecycle: invalid config fails fast; disconnect → reconnect with a new `streamId`; adapter closed on shutdown. — `test_acquisition_service.py::test_invalid_device_configuration_fails_without_retry`, `::test_disconnect_reconnects_with_a_new_stream_and_closes_adapters`, `::test_connection_failures_back_off_and_give_up_after_max_attempts`, `::test_stop_cancels_cleanly_and_is_idempotent`; `test_config.py::test_invalid_environment_fails_fast`; `test_api.py::test_disconnecting_clients_release_subscriptions_and_shutdown_stops_acquisition`.
- [x] Disallowed `Origin` rejected; server bound to `127.0.0.1`; no new egress. — `test_api.py::test_disallowed_origin_is_rejected`; smoke test (HTTP 403 for `Origin: http://evil.example`); `neuro-engine:serve` binds `--host 127.0.0.1`; no outbound network calls added.
- [x] Desktop validates every message; malformed/unsupported/stale/reconnect states handled; no samples in React state. — `eegStreamClient.spec.ts` (9 tests: valid flow, malformed JSON/schema/semantic/binary, integrity, stale, reconnect backoff with cap, new stream, incompatible version, stop/start, socket construction failure); `app.spec.tsx` (App connects to `/ws/v2/eeg`, shows status, closes on unmount). Samples flow only through `EegStreamClient.onBlock`; `EegStreamSnapshot` has no sample field.
- [x] `yarn nx run-many -t lint test typecheck build`, engine pytest/ruff and governance checks pass. — see Validation Evidence (including the PR-gate dry run after acceptance).

## Implementation Summary

- **Protocol (`packages/protocol`):** canonical `schemas/eeg-stream.v2.schema.json`; generated `src/generated/eeg-stream.v2.ts` (`scripts/generate-types.mjs`, `generate-types` / `check-generated` targets, drift spec); `validate.ts` (Ajv 2020 + semantic layer, error kinds `json|schema|unsupported-version|semantic`, no value echo); `integrity.ts` (`StreamIntegrityTracker`, `sampleTimeUs`); fixtures `fixtures/v2/` (32 message cases, 7 integrity scenarios); TS project config for test/typecheck; README. v1 `EEGFrame`/`DeviceStatus` removed.
- **Engine (`services/neuro-engine`):** `acquisition/` (`DeviceAdapter` protocol, typed errors, immutable `SampleBlock`, `MonotonicClock`/`VirtualClock`, deterministic `SyntheticEegAdapter` with drop/disconnect faults, `AcquisitionService` state machine with reconnect backoff); `streaming/hub.py` (`StreamHub`, live-view and lossless policies); `protocol/` (Pydantic v2 mirror, semantic checks, converters, Python integrity tracker); `api/` (`/health`, `/api/v2/stream`, `/ws/v2/eeg` with Origin allowlist); `app.py` lifespan-owned acquisition; `config.py` env settings. `/ws/eeg` v1 removed. Dependencies: `pydantic` (declared), `jsonschema` (dev). `project.json` test inputs include protocol schemas/fixtures. `tests/test_health.py` updated to the new health shape (same 16 ch / 125 Hz assertions); 8 new test modules.
- **Desktop (`apps/desktop`):** `stream/eegStreamClient.ts` (framework-free client), `stream/useEegStream.ts` (`useSyncExternalStore`, `VITE_NEURO_ENGINE_WS_URL`), `stream/StreamStatusPanel.tsx` (connection/health, provenance label, units/reference/layout, rates, integrity counters, protocol errors); `app/app.tsx` uses them; the placeholder sphere no longer maps a sample value to "activity" and is labelled as not representing brain activity. `app/app.spec.tsx` replaced with an App-level test.
- **CI:** `.github/workflows/ci.yml` runs `lint test typecheck build`.
- **Docs:** `docs/architecture/OVERVIEW.md` (implemented acquisition path), `packages/protocol/README.md`, `services/neuro-engine/README.md`, ADR-0008 implementation notes.

## Validation Evidence

All commands run on 2026-10-30 from the repository root on macOS (darwin), Python 3.12.16, `NX_DAEMON=false`, with `--skip-nx-cache` where shown.

| Command | Result |
| --- | --- |
| `yarn nx show projects` | `neuro-engine`, `@neuro-observatory/protocol`, `desktop` |
| `yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache` | Passed for 3 projects. Protocol: 48 Vitest tests passed. Desktop: 14 Vitest tests passed. Engine: 139 pytest passed, ruff "All checks passed!". Desktop `vite build` succeeded with a chunk-size warning (1,297.74 kB minified / 358.42 kB gzip > 500 kB). One pytest warning: `StarletteDeprecationWarning` (httpx with `starlette.testclient`). |
| `yarn nx run @neuro-observatory/protocol:check-generated --skip-nx-cache` | Passed (no drift) |
| `cd services/neuro-engine && uv run pytest` (×5 during development) | 139 passed each run, ~4 s; no flaky real-time tests observed |
| `python3 -m unittest discover -s tools/governance/tests` | 5 tests OK |
| `python3 tools/governance/check_governance.py --all` | Passed |
| PR-gate dry run: `check_governance.check_change_set()` over `git diff --name-only --diff-filter=ACMR` + untracked files (101 paths), before owner acceptance | Failed as expected: no completed WORK record; ADR-0008 status must be Accepted. No restricted/sensitive paths. |
| Same dry run, `--all` and governance unit tests, after owner acceptance and moving this record to `completed/` | Dry run passed (101 paths); `--all` passed; 5 unit tests OK |
| Manual smoke test: `uv run uvicorn neuro_engine.main:app --host 127.0.0.1 --port 18765` + Python `websockets` client for 3 s (script outside the repo) | `/health` ok, `streaming`, 16 ch, 125.0 Hz, `synthetic: true`; disallowed Origin → HTTP 403; 1 metadata, 4 status, 15 blocks; every message parsed by the Python v2 validator; 375 samples in 3.01 s (124.8 samples/s); integrity counters all zero anomalies; engine `effectiveSampleRateHz` 124.977. Server process stopped afterwards. |

Not run: GitHub Actions CI (nothing committed or pushed); browser-level manual check of the desktop UI against a live engine (covered by component tests with a stub WebSocket and the engine smoke test, not by an end-to-end browser run).

## Risks and Follow-ups

Risks / known gaps:

- Synthetic timestamps are nominal by construction; they say nothing about real device latency or drift. Physical devices will need `host-receipt-fitted` or `device-clock` timing (01B).
- Ajv compiles validators with `new Function`; a strict Tauri CSP would block it (follow-up: Ajv standalone precompilation).
- The Pydantic mirror is hand-maintained; drift is caught only by the shared fixtures, so new schema rules need new fixtures.
- JSON transport at 16 ch × 125 Hz is cheap; much larger channel counts or rates may require binary frames (new ADR).
- Desktop bundle exceeds Vite's 500 kB warning (mostly Three.js); not addressed here.
- Breaking change: any v1 client stops working (none known).

Follow-ups (not in scope): BrainFlow/OpenBCI adapter with device timing (01B); lossless recorder and file format; replay `DeviceAdapter`; waveform ring buffer on `EegStreamClient.onBlock`; DSP; signal-quality fields once measurable; device control API; clock-drift fitting; Ajv standalone build; SHA-pinned GitHub Actions and Dependabot for uv; `neuro-engine` console-script entry point and `pyproject` description; `strict` in `tsconfig.base`; migrate tests off the deprecated `starlette.testclient` httpx path; remove the Nx `nx-welcome.tsx` scaffold.

## Human Review

Owner approved the Milestone 01A plan for implementation on 2026-10-30. After reviewing the verification report, the owner explicitly accepted ADR-0008 on 2026-10-30 (chat), and this record was then marked Completed and moved to `docs/work/completed/`. Nothing has been committed, pushed or merged; the change set still requires owner review in a PR and CI on GitHub.
