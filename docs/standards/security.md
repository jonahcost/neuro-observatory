# Security, privacy, and electrical-safety controls

## Data classification

**Restricted local-only:** raw EEG and sensor samples, MRI/DICOM/NIfTI, identifiable images/video, biometric signatures, eye tracking and trained models derived from personal physiological data. Do not put in Git, PR attachments, model prompts or cloud telemetry.

**Safe in repository:** code, architecture documents, device mockups, fake/synthetic signals, anonymized tiny test fixtures known to be generated synthetically, public reference templates with licenses.

## Controls

- Only use loopback HTTP/WebSockets unless an authorized ADR justifies network access. No remote debugging/public tunnels without explicit consent.
- No embedded credentials or tokens. Secrets go into local ignored config; review logs and test artifacts for accidental leakage.
- Encrypt personal storage and backups; use OS disk encryption/key management. Plan retention/deletion/backup restores before collecting long sessions.
- No data sent to LLMs, hosted inference, observability, analytics or CI by default. `.cursorignore` excludes sensitive paths from editor/agent context **but not terminal or MCP access**; configure Cursor privacy and tool approval settings separately.
- Custom EEG acquisition electronics are not safe merely because source schematics are public. Validate isolated power, patient leakage/fault paths, ESD, contact safety and emergency disconnect through qualified review; no human-contact tests until cleared.
- No invasive stimulation or electrical actuation. This project only passively observes signals.
