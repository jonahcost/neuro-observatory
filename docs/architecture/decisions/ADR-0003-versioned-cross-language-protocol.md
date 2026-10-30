# ADR-0003: Evolve shared EEG contracts toward a versioned neutral schema

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

The initial `packages/protocol` defines TS interfaces and Python emits JSON. Compile-time TS types do not validate incoming Python payloads.

## Decision

Keep the current bootstrap interface, then select a language-neutral schema (JSON Schema or Protobuf) in a feature ADR; generate or validate producer and consumer, with explicit versions and migrations.

## Alternatives Considered

Maintain duplicated hand-written types indefinitely (drift), or rewrite all transports prematurely (unnecessary risk).

## Consequences

More predictable compatibility, additional schema tooling and migration work. Current TS types are not runtime safety guarantees.

## Validation and Rollback

Add contract fixtures and compatibility tests for malformed packets, units, ordering and timestamps; revert a breaking transport change with backward-compatible adapter support.
