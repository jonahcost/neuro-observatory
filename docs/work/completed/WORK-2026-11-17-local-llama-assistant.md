# WORK-2026-11-17-local-llama-assistant: Local llama.cpp assistant runtime

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0017-local-llama-assistant.md`

## Objective

Supervise an optional loopback llama-server from the neuro-engine, and keep findings and typed commands working when that model is absent.

## Scope

In scope: `NEURO_ENGINE_ASSISTANT` defaulting off, checksum install of a local GGUF, a child process bound to `127.0.0.1:8010`, prompt text limited to finding summaries, timeout and cancel when the session generation changes.

Non-goals: downloading weights, sending raw EEG or meshes to the model, a desktop socket to llama-server, and marking the ADR Accepted.

## Acceptance Criteria

- [x] Tests and `from_env({})` do not spawn llama-server.
- [x] Install checks sha256 and does not fetch a file.
- [x] A missing model still answers "which channels changed most?" from current findings.
- [x] A generation mismatch cancels the intent. Unknown finding ids are refused.
- [x] Prompts used by the runtime contain finding summaries, not sample arrays.

## Implementation Summary

`LlamaRuntime` stays unavailable unless the assistant flag is on and a verified manifest exists. `AssistantService` validates every snapshot and intent result against assistant v1 before it leaves the process. The desktop shows the unavailable-model sentence and still sends the closed command lexicon to the engine.

## Validation Evidence

- `cd services/neuro-engine && uv run pytest tests/test_model_runtime.py tests/test_assistant_commands.py tests/test_assistant_contract.py -q --tb=line` — included in the focused run of 56 passed, and in the full run of 434 passed.
- `cd services/neuro-engine && uv run ruff check .` — All checks passed.
- No GGUF was downloaded and llama-server was not started during these checks.

## Risks and Follow-ups

Time to first token was not measured because weights are not installed. Metal GPU layers stay at the manifest default of 0 until a browser frame measurement says otherwise. The owner accepted ADR-0017 on 2026-11-17 with that follow-up still open.

## Human Review

The owner directed implementation of the 04A plan on 2026-11-17 and accepted ADR-0017 on 2026-11-17.
