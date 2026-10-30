# Install these governance files into your existing monorepo

This package is an **overlay**, not a replacement repository. It does **not** modify your existing Nx/Yarn/uv application or Python code. Review the file list before copying. The only new GitHub workflow is `.github/workflows/governance.yml`; your existing `ci.yml` remains unchanged.

From your Mac:

```bash
cd ~/sde/jc/neuro-observatory
unzip -l ~/Downloads/neuro-observatory-agent-governance.zip
unzip -n ~/Downloads/neuro-observatory-agent-governance.zip -d .
git status --short
python3 -m unittest discover -s tools/governance/tests -v
python3 tools/governance/check_governance.py --all
```

If `INSTALL.md` already exists, unzip with `-n` leaves the existing file unchanged. Prefer a new branch for review; don't push directly to `main`.

```bash
git switch -c chore/agent-governance
git add AGENTS.md CLAUDE.md .cursorignore .cursor .github docs tools/governance INSTALL.md
git diff --cached --stat
```

Before opening PR: read the initial ADRs and work record, run full Nx/Yarn/uv checks, confirm the new governance CI is compatible with your existing workflow, and update the work record's evidence. Owner approval is needed before marking any newly proposed ADR Accepted.

In GitHub, configure a `main` branch ruleset requiring a PR, required `architecture-governance` and existing CI status checks, and human review if your repository plan supports it. **Files alone cannot enforce branch protection.** Keep the only write access with the owner; disable automatic agent pushes/merges. Consider code owners and secret scanning depending on repo plan.

Use `python3 tools/governance/new_work.py --slug <slug> --title "<title>"` for the next chunk. Before a later PR is considered done, the agent must update/move the work record to `completed` and obtain approval to mark ADR Accepted.
