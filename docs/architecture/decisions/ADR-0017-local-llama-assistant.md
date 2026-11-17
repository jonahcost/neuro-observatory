# ADR-0017: Local llama.cpp assistant runtime

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner (implementation of the attached 04A plan was directed on 2026-11-17; this record stays Proposed until the owner marks it Accepted)
- Related Work: `docs/work/completed/WORK-2026-11-17-local-llama-assistant.md`, `docs/work/completed/WORK-2026-11-17-assistant-benchmark.md`
- Supersedes: None.

## Context

ADR-0016 leaves questions and free-form commands unanswered when no model is installed. The desktop is Vite on a loopback engine. There is no Tauri shell and no packaged model runtime. `docs/standards/security.md` forbids sending data to a hosted LLM. llama.cpp `llama-server` binds to `127.0.0.1` by default and accepts `response_format` `json_schema` on `POST /v1/chat/completions`.

## Decision

1. The neuro-engine may spawn `llama-server` as a child bound to `127.0.0.1` on port 8010 (override `NEURO_ENGINE_ASSISTANT_PORT`). The browser never opens that port.
2. Weights live under the existing per-user data directory. `neuro-engine assistant install` records a manifest with filename, sha256, quantization, context, and the server binary path. It does not download. Startup verifies the checksum and, on failure, leaves the model unavailable without stopping acquisition.
3. Prompts contain the question, the closed command lexicon, and finding summaries already returned to the UI. They do not contain raw EEG, MRI, or mesh buffers. Model JSON is validated again. Unknown finding ids are dropped and the reply says the claim could not be tied to a current finding.
4. A request times out after 30 s. A session generation change cancels the in-flight task and discards a late reply. Template findings and lexicon commands keep working when the runtime is absent.
5. The primary candidate is a 3B-class instruct GGUF at `Q4_K_M` (`Qwen2.5-3B-Instruct` unless a Mac benchmark names another file of that class). The fallback is `Qwen2.5-0.5B-Instruct` or `Llama-3.2-1B-Instruct` at `Q4_K_M`. Neither file is vendored. The benchmark chooses the installed file.

## Alternatives Considered

- Call a hosted chat API. Rejected: raw and derived session data stay on the machine.
- Run the model in the browser. Rejected: weights and the EEG session would share the renderer process, and the page would need its own runtime.
- Block the assistant until weights exist. Rejected: band-power findings and typed lexicon commands are useful without a model.

## Consequences

A new local process and port exist only when a checksum-verified manifest is present. Grammar-constrained decoding adds latency. Metal offload shares the GPU with the browser scene; the benchmark can force CPU inference. This ADR does not add Tauri packaging.

## Validation and Rollback

CI uses an injected transport, not llama.cpp. Missing binary, bad checksum, timeout, cancel, and an unknown finding id are tested. Delete the manifest and stop the child to roll back; acquisition and template findings remain.
