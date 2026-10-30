# ADR-0005: Separate structural MRI, measured EEG, and model estimates

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

A personalized brain mesh and EEG inverse solution have different provenance and resolution; 3D imagery is easily misread as direct neural imaging.

## Decision

Generate subject meshes from structural T1 MRI (when available). Keep electrode coordinates/head model/inverse operator separate, versioned, and identified in every source-estimate frame. Label sensor observations, estimates and ML classifications distinctly.

## Alternatives Considered

Paint raw electrodes onto a brain surface as if they directly measure cortical vertices; treat MRI as real-time functional imaging.

## Consequences

Scientific interpretability and reproducibility improve, with greater calibration UX and metadata burden.

## Validation and Rollback

Validate coordinate transforms and model identity, display missing/low-quality data honestly. Fall back to a labeled generic model or scalp-only visualization when personalized estimation is not valid.
