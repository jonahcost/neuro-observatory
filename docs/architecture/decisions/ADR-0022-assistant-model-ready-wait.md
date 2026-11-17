# ADR-0022: Wait long enough for a cold local model to become ready

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner (this record stays Proposed until the owner marks it Accepted)
- Related Work: `docs/work/completed/WORK-2026-11-17-assistant-model-ready-wait.md`
- Supersedes: None. ADR-0017 still owns the loopback `llama-server`, the checksum, and the 30 s request timeout.

## Context

`LlamaRuntime` spawned `llama-server` for the installed 2 GB Qwen2.5-3B Q4_K_M file, then polled `/health` for about 5 seconds. The process was still loading, so the engine set `model` to `unavailable` and never checked again. The server later answered `/health` with 200 while the snapshot stayed unavailable.

## Decision

The engine keeps polling `/health` for up to 120 seconds after spawning `llama-server`. A process that exits, or that is still not healthy at the deadline, stays `unavailable` with reason `runtime-missing`. Acquisition still does not wait on this poll.

## Alternatives Considered

- Leave the 5 second poll. Rejected: a cold load of the candidate model does not finish in that window.
- Block engine startup until the model is ready. Rejected: EEG acquisition must start even when the model is slow or absent.

## Consequences

The first snapshot after a cold start can say `starting` for up to two minutes, then `ready` or `unavailable`. A later request still times out after 30 seconds.

## Validation and Rollback

A unit test covers a late health response and a deadline miss. Restoring the 20-iteration poll returns the previous behavior.
