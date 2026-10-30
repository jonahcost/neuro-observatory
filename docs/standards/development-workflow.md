# Agent development lifecycle

## Definition of a chunk

A bounded, independently reviewable change with one purpose, explicit expected behavior, tests and a rollback route. Do not combine EEG device integration with ML model training or a framework migration in one chunk.

## Required sequence

1. **Inventory:** capture relevant current behavior, impacted paths, tests, accepted ADRs and `git status`. Never remove unrelated work.
2. **Work record:** run `python3 tools/governance/new_work.py --slug <slug> --title "<title>"`; edit scope, measurable acceptance criteria, dependencies, risk and verification plan.
3. **Decision:** the generator creates a proposed ADR. Document context, meaningful options, selected option, consequences, reversibility and data/safety implications. Link it to the work record. Reuse accepted decisions as context, but write a new ADR for each meaningful implementation chunk as the owner requested. Small chunks may document a narrow extension of an existing decision, not fabricate a sweeping decision.
4. **Owner gate:** request explicit acceptance before changing infrastructure boundaries, protocols, persisted formats, hardware safety, deployment/security, privacy, costly purchases or irreversible changes. Mark `Status: Accepted` only after the owner agrees.
5. **Code and test:** implement smallest slice, update docs, run targeted tests. No auto-push, no destructive edits, no hidden dependency changes.
6. **Record actual evidence:** terminal commands, success/failure, measurable outcomes, regression/replay checks, known defects, why unrun tests were skipped. Distinguish simulation from real measurements.
7. **Complete work record:** set `Status: Completed`, move active record to `docs/work/completed/`, link accepted ADR(s), record change summary and unresolved follow-up issues. Open PR with template; CI enforces one changed completed work record and accepted ADR for implementation/config changes.
8. **Merge:** project owner checks actual code, ADR and evidence, and merges. Do not claim CI proves safety or scientific accuracy.

## Exception policy

No automatic bypass of the governance gate for implementation/configuration changes. Documentation-only PRs can skip a work/ADR pair. To change the governance policy itself, follow the standard ADR + completed work record process. Emergency fixes still require retrospective ADR and work evidence in the same PR before merge.

## Definition of done

- Acceptance criteria demonstrably satisfied; no fabricated test output.
- Build/lint/tests appropriate to changed projects pass; CI green.
- Protocol and migration compatibility addressed where relevant; time/units/data provenance maintained.
- Raw acquisition unaffected by UI failures; safe local defaults retained.
- Owner-approved ADR accepted, completed work record linked, known gaps disclosed.
