# ADR-0006: Use a canonical brain scene with interchangeable renderers

- Status: Accepted
- Date: 2026-10-29
- Decision Owner: Project owner (recorded from established project direction; re-review on integration)
- Related Work: `docs/work/completed/WORK-2026-10-29-governance-baseline.md`
- Supersedes: None

## Context

The project needs browser/desktop visualization, a future light-field display, and optional gesture input.

## Decision

Define one versioned `BrainSceneFrame` independent from Three.js or Looking Glass SDK. The desktop and holographic adapters consume it; gesture commands modify scene state rather than acquisition.

## Alternatives Considered

Embed light-field SDK types into neuroscience processing, or build separate source-estimation pipelines per display.

## Consequences

Allows multiple displays, at cost of scene schema and display synchronization work.

## Validation and Rollback

Test equivalent scene state on headless or mocked renderers and ensure FPS changes do not change recorded EEG. Revert an adapter without changing sensor/scene producer.
