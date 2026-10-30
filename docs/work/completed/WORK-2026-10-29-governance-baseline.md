# WORK-2026-10-29-governance-baseline: Establish agent governance baseline

- Status: Completed
- Owner: Project owner (review required when integrating package)
- ADRs: `docs/architecture/decisions/ADR-0007-work-unit-adrs-and-pr-gates.md`

## Objective

Provide a reviewed, testable governance overlay for multiple Cursor AI agents and a repeatable ADR/work process.

## Scope

New `AGENTS.md`, `CLAUDE.md`, `.cursorignore`, `.cursor/rules/*`, `docs/standards/*`, `docs/architecture/*`, `docs/work/*`, `docs/prompts/*`, `tools/governance/*`, `.github/workflows/governance.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`. No changes to current application source or Nx config.

## Acceptance Criteria

- [x] Model-agnostic root and scoped agent rules provided
- [x] Architecture decisions and work record templates provided
- [x] Governance PR checker, generator and tests provided
- [x] Safety/privacy/scientific limits and explicit owner-review boundaries documented
- [x] Existing CI and project source remain untouched by the overlay

## Implementation Summary

A package overlay introduces codified standards, initial retrospective decisions, per-chunk work generation, a structural review gate, and a separate least-privilege governance CI workflow.

## Validation Evidence

Verified before delivery: `python3 -m unittest discover -s tools/governance/tests -v` and `python3 tools/governance/check_governance.py --all` in the isolated overlay directory. **Local host Nx tests and GitHub CI have NOT been executed against the user's checkout.** Run them after installation and record the actual outcomes in the PR.

## Risks and Follow-ups

GitHub branch rulesets must be enabled manually; text instructions and CI structure alone are not authorization. Review retrospective accepted ADRs against actual repo before merging. Configure a protected-branch rule and required check. Correct baseline work evidence if local integration reveals issues.

## Human Review

Project owner must inspect this package and approve adoption in the PR; agent-generated initial decisions reflect earlier project selections and can be revised prior to merge.
