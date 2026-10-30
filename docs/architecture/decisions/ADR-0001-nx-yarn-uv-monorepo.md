# ADR-0001: Use a single Nx monorepo with Yarn and uv

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

The system needs React, shared TS contracts, Python DSP and future hardware/display code; the existing repository is already Nx/Yarn-based, with a Python uv service.

## Decision

Keep one private Git repository. Nx coordinates targets, Yarn 4 manages JS/TS, uv manages Python; Rust/Tauri may use Cargo. Services do not become fake JS packages.

## Alternatives Considered

Separate repositories increase cross-version coordination. A plain workspace lacks consistent cross-language task orchestration.

## Consequences

Consistent change history and shared contracts; requires careful Nx project/task metadata and CI ownership.

## Validation and Rollback

Confirm `yarn nx show projects`, lockfiles and Python tests. Roll back tooling migrations by reverting the specific migration PR, not rebuilding the repository.
