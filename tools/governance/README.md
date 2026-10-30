# Governance automation

- New work/ADR pair: `python3 tools/governance/new_work.py --slug render-eeg-waveforms --title "Render live EEG waveforms"`
- Validate all accepted ADRs/completed work: `python3 tools/governance/check_governance.py --all`
- Simulate PR check against `main`: `python3 tools/governance/check_governance.py --base origin/main --head HEAD`
- Tests: `python3 -m unittest discover -s tools/governance/tests -v`

CI requires accepted ADR and completed WORK record changed in any PR modifying app, service, package, pipeline, hardware, Nx/Yarn configuration, Cursor rules, agent policy, CI or tools. Documentation-only PRs are exempt. It does not verify human consent, electrical safety, model validity or scientific provenance automatically. GitHub branch protection must be enabled separately.
