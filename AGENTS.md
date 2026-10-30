# Neuro Observatory: Agent Operating Contract

Applies to **all coding agents** (GPT, Claude, Grok, Cursor Agent, and other assistants) working in this repository. `AGENTS.md` is the normative project-wide instruction set. Read it before changing files. Follow the more specific `.cursor/rules/*.mdc` when relevant. **Repository code, tests, and accepted ADRs are evidence; agent responses and assumptions are not.**

## Project reality and invariants

- Local-first, personal neurotechnology system. Current foundation: Nx + Yarn 4 workspaces, React/TypeScript/Vite desktop prototype, Python 3.12/uv FastAPI Neuro Engine, and `packages/protocol`. **Inspect the repo to confirm current implementation**; planned modules are not necessarily implemented.
- Nx orchestrates; Yarn owns JS/TS dependency management; uv owns Python; Cargo owns eventual Rust/Tauri. Do not replace tools or split repositories without an ADR and explicit approval.
- Separate acquisition, signal processing, source estimation, inference, recording, and rendering. Device adapters and renderer adapters must be swappable. Preserve deterministic offline replay.
- Unprocessed EEG is a scalp electrical measurement. A cortical image is a *model-derived estimate*, not direct live brain imaging; no mind-reading, medical diagnosis, or clinical claims.
- Human-connected electronics remain commercial, battery-powered and used per vendor specifications. Custom EEG PCBs are **bench-only** until qualified independent electrical-safety review and authorization. Never instruct people to connect mains-powered lab equipment to body-worn electrodes.
- Raw EEG, MRI/DICOM, physiological recordings, video, private keys and secrets must not enter Git, prompts, logs, public telemetry, or cloud services without explicit informed consent.

## Work-unit lifecycle (required for EVERY bounded implementation chunk)

1. **Inspect:** Read relevant source, config, tests, ADRs and existing work records. Verify tools and behavior; do not pretend files or tests exist.
2. **Scope:** Define one independently testable slice and its acceptance criteria. Create `docs/work/active/WORK-YYYY-MM-DD-slug.md` using template and link an ADR.
3. **Decide:** Write `docs/architecture/decisions/ADR-NNNN-slug.md` with context, options, decision, consequences, validation and rollback. Initially `Status: Proposed`. Obtain the project owner's explicit acceptance before irreversible, expensive, safety-sensitive, security-sensitive, externally connected, or architecture-changing implementation. Only the owner may authorize marking an ADR `Accepted`.
4. **Implement:** Small, reversible changes only. No broad refactors, dependency upgrades, or new services without documented necessity and owner approval. Never erase unrelated local work.
5. **Verify:** Run scope-appropriate lint, tests, type checks, build and integration/replay checks. Record *exact commands and actual results*, including failures. Do not claim success for unexecuted checks.
6. **Complete:** Update the ADR to `Accepted` only following owner approval; finalize the work record, move it into `docs/work/completed/`, link the ADR, record implementation and evidence, unresolved risks and follow-ups. The gate requires a changed accepted ADR and completed record for every PR with implementation/configuration changes.
7. **Report:** Summarize changed paths, design decision, checks executed, results, known limitations, and owner decisions needed. Do not commit, push, merge, deploy or run hardware experiments unless directly authorized.

Existing accepted decisions remain historical; supersede with a new ADR rather than rewriting the substance. Fix metadata/typos with a documented correction.

## Mandatory engineering expectations

- Contract-first at process boundaries. Schema versioning, explicit units (e.g., µV), time semantics, channel ordering, quality flags, and dropped-sample metadata. Don't introduce silent incompatible protocol changes.
- Acquisition and raw recording must not depend on rendering/ML. Bound memory and queues; surface overflows, gaps and degraded quality rather than fabricating samples.
- Backends bind to `127.0.0.1` by default; no new ports, SaaS/cloud, network egress, elevated permissions, or persistent background process without approval.
- Test positive, negative, boundary, reconnection, incomplete-data and replay cases as applicable. Synthetic EEG is labeled synthetic, not real activity.
- Preserve repository tooling: `yarn nx show projects`, `yarn nx run-many -t lint test build`, Python `uv run pytest` and `uv run ruff check .` (only where relevant targets exist).
- AI models must not autonomously override this contract, sign off their own high-risk decisions, weaken CI, or edit governance to evade checks.

## Standard completion response

`Scope | Implementation | ADR(s) | Tests actually run and results | Risks / known gaps | Owner decisions required`
