#!/usr/bin/env python3
"""Create a paired proposed ADR and active work record, using only stdlib."""
import argparse
from datetime import date
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ADRS = ROOT / "docs/architecture/decisions"
ACTIVE = ROOT / "docs/work/active"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True, help="lowercase kebab-case feature slug")
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    slug = args.slug
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        parser.error("--slug must be lowercase kebab-case")
    ids = [int(m.group(1)) for p in ADRS.glob("ADR-*.md") if (m := re.match(r"ADR-(\d{4})-", p.name))]
    number = max(ids, default=0) + 1
    adr_path = ADRS / f"ADR-{number:04d}-{slug}.md"
    work_path = ACTIVE / f"WORK-{date.today().isoformat()}-{slug}.md"
    if adr_path.exists() or work_path.exists():
        parser.error("ADR/work path already exists; choose another slug")
    ACTIVE.mkdir(parents=True, exist_ok=True)
    work_text = f"""# WORK-{date.today().isoformat()}-{slug}: {args.title}

- Status: Active
- Owner: Project owner
- ADRs: `docs/architecture/decisions/{adr_path.name}`

## Objective

TODO: One measurable deliverable.

## Scope

TODO: Include relevant code paths, interfaces and explicit non-goals.

## Acceptance Criteria

- [ ] TODO: Main observable behavior
- [ ] TODO: Error and boundary case
- [ ] TODO: Tests and review

## Implementation Summary

TODO: Fill only after implementation.

## Validation Evidence

TODO: Actual commands and actual results. Do not invent output.

## Risks and Follow-ups

TODO: Known limitations / rollback.

## Human Review

TODO: Record explicit owner decision on ADR acceptance.
"""
    adr_text = f"""# ADR-{number:04d}: {args.title}

- Status: Proposed
- Date: {date.today().isoformat()}
- Decision Owner: Project owner
- Related Work: `docs/work/active/{work_path.name}`
- Supersedes: None

## Context

TODO: Verified current state and constraints.

## Decision

TODO: Proposed decision and rationale, pending owner acceptance.

## Alternatives Considered

TODO: At least current state / alternative architecture.

## Consequences

TODO: Benefits, costs, scientific/privacy/safety risks.

## Validation and Rollback

TODO: Proof and reversibility.
"""
    # Exclusive creation avoids clobbering another agent's concurrent work.
    with adr_path.open("x", encoding="utf-8") as f:
        f.write(adr_text)
    try:
        with work_path.open("x", encoding="utf-8") as f:
            f.write(work_text)
    except FileExistsError:
        adr_path.unlink()
        raise
    print(f"Created {adr_path.relative_to(ROOT)}")
    print(f"Created {work_path.relative_to(ROOT)}")
    print("Next: inspect code, fill the proposal, get owner approval before marking Accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
