# Infrastructure and DevEx standards

- Monorepo: Nx project graph and tasks; Yarn 4 workspaces with `node-modules` linker for JS/TS; uv with Python 3.12 for services; Cargo as needed for future Rust/Tauri.
- Treat Python projects as Nx-managed task projects, **not** fake Yarn workspaces. Add `project.json` with `serve` uncached and explicit lint/test targets.
- Keep local backend bound to `127.0.0.1` and do not expose raw EEG or MRI over a network interface. Cloud integrations require owner-approved privacy/security ADR.
- Define process startup, readiness/health, shutdown, error classification, resource limits and reconnection. No infinite unbounded buffers or uncontrolled background daemons.
- Tests must not require actual EEG hardware, MRI images, internet, or paid displays in CI. Provide simulator/fakes.
- Avoid nondeterministic target caching. Live/serve targets never cached; include code, configs and dependency lockfiles in appropriate build/test inputs.
- Add dependency or framework only after making the benefit, resource impact, license and maintenance cost explicit in the ADR. Security upgrades remain tightly scoped.
- No telemetry by default. Redact or avoid secrets, physiological readings, identifying paths and patient metadata in logging. Logs use IDs and device status, not data dumps.
- Prefer local files and SQLite for metadata before provisioning cloud databases. Strong encryption and backups for private data.
- After modifying workspace configuration inspect `yarn nx show projects`, `yarn nx graph`, and the relevant targets; run `yarn nx run-many -t lint test build` when available.
- CI uses read-only permissions and explicit status checks; humans configure protected branches in GitHub.
