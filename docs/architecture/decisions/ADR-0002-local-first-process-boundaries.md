# ADR-0002: Keep acquisition local and decouple runtime processes

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

Personal anatomical and physiological data are sensitive. Visualization and ML can stall independently from data acquisition.

## Decision

Default to loopback APIs and local recordings. Device adapters, DSP, recorder, inference and presentation are separate modules, with services split into processes only when justified.

## Alternatives Considered

Cloud microservices offer remote access at privacy/operations cost. A single UI-bound acquisition loop is simpler initially but risks lost raw samples.

## Consequences

Simpler operations, offline capability and clear failure domains; local lifecycle/readiness/recovery still need engineering.

## Validation and Rollback

Test no external egress by default, processing after UI disconnection, bounded queues and clean shutdown. If later network exposure is required, supersede with a privacy/security ADR.
