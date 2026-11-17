# WORK-2026-11-17-assistant-model-ready-wait: Wait for a cold llama-server load

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0022-assistant-model-ready-wait.md`

## Objective

Keep the assistant model in `starting` until `llama-server` answers `/health`, for long enough to load the installed 2 GB GGUF.

## Scope

In scope: the ready poll in `LlamaRuntime`.

Non-goals: changing the 30 s request timeout, GPU layers, or the install command.

## Acceptance Criteria

- [x] A health check that succeeds after the old 5 second window still marks the model ready.
- [x] A process that never becomes healthy is marked unavailable when the deadline passes.
- [x] Acquisition startup is not blocked on this poll. `startup` still schedules the poll and returns.

## Implementation Summary

The ready poll now runs until `/health` succeeds or 120 seconds pass. It is still a background task, so acquisition starts without waiting for the model.

## Validation Evidence

- `cd services/neuro-engine && uv run pytest tests/test_model_runtime.py -q --tb=short` — 5 passed.
- `cd services/neuro-engine && uv run ruff check src/neuro_engine/assistant/runtime.py tests/test_model_runtime.py` — all checks passed.
- Before this change, `curl http://127.0.0.1:8010/health` returned 200 while `/api/assistant/v1/snapshot` reported `"model": "unavailable"`.

## Risks and Follow-ups

ADR-0022 stays Proposed until the owner accepts it. The engine process that produced the unavailable snapshot is still running the old 5 second poll until it is restarted.

## Human Review

The owner hit `model: unavailable` while `llama-server` was already healthy on 2026-11-17. This record does not mark ADR-0022 Accepted.
