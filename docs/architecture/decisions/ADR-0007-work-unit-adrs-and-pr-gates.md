# ADR-0007: Require ADRs and evidence for each implementation chunk

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

Multiple AI models in Cursor may make inconsistent architectural choices or assert unverified completion. The user explicitly wants infrastructure guardrails and ADRs on every completed chunk.

## Decision

Maintain a root `AGENTS.md`, scoped Cursor `.mdc` rules, paired work/ADR templates, an agent work lifecycle, and a PR CI check that checks changed completed records and accepted ADRs. Human review remains authoritative.

## Alternatives Considered

Only use natural-language prompts (not enforceable), or require lengthy speculative design docs for trivial changes (high overhead).

## Consequences

Creates consistent decision history and CI visibility with some paperwork. Structural checks cannot prove human approval or scientific/electrical safety.

## Validation and Rollback

Run governance unit tests and `check_governance.py --all`; verify it rejects a code-only PR and accepts a documented PR. Change the governance process only in an owner-approved follow-up ADR.
