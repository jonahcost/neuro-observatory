# Architecture Decision Records

One ADR per meaningful completed work chunk, even when narrowly extending an existing decision. ADRs preserve **why**, not just **what**. Starting ADRs record already-chosen direction, not claims of complete feature implementation.

## Naming and states

`ADR-0001-short-slug.md` and subsequent monotonic numbers; `Status: Proposed | Accepted | Superseded | Rejected`.

- Proposed during design; human explicitly accepts before code for consequential changes.
- Accepted ADRs are immutable in their decision substance; supersede with a new ADR. Minor corrections are permitted.
- Each ADR links `Related Work`, lists alternatives, consequences and rollback plan.
- When multiple agents work concurrently, reserve or reconcile ADR numbers on branch rebase; never silently overwrite an existing ADR.

Run `python3 tools/governance/new_work.py --slug example --title "Example"` to create the paired proposed ADR and work record.
