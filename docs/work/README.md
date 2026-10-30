# Work records

- `active/`: agent is designing or implementing the chunk, status Active.
- `completed/`: implementation and verification concluded, status Completed, links to a human-accepted ADR.
- Every implementation/configuration PR must change at least one completed work record and at least one accepted ADR (the repository's review gate enforces structural presence).
- Documentation-only PRs do not require these records.
- The gate is not proof of human acceptance; repository branch protections and project owner review are still required.
- Create a new pair: `python3 tools/governance/new_work.py --slug first-real-feature --title "First real feature"`.
