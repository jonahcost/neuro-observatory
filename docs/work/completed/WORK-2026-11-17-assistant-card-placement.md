# WORK-2026-11-17-assistant-card-placement: Assistant card beside the live brain

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0019-assistant-card-placement.md`

## Objective

Move the EEG assistant into its own collapsible card immediately left of the live brain, and keep the display inspector and waveform dock where they are.

## Scope

In scope: the desktop workspace grid, the assistant card chrome, and the app test that checks order and collapse.

Non-goals: assistant protocol, findings, commands, and display-mode behavior.

## Acceptance Criteria

- [x] The assistant region is a card to the left of the live brain. Display modes stay in the right inspector.
- [x] Collapse hides the command field and expand shows it again. The EEG socket stays the one already open.
- [x] Desktop tests cover the order and the collapse control.

## Implementation Summary

The workspace is three columns: the assistant card, the live brain with the waveform dock beneath it, and the display inspector. The card header collapses the body to a short rail at the top of that column. The assistant poll stays mounted while the body is hidden.

## Validation Evidence

- `yarn nx run desktop:test -- src/app/app.spec.tsx` — 4 passed.
- `yarn nx run desktop:lint` — passed.
- `yarn nx run desktop:typecheck` — passed.
- Browser at `http://127.0.0.1:4200`: the open card measured x=12, width 310, and the live brain measured x=334. Collapsed, the rail was x=12, width 54, and the brain moved to x=78 and widened to 1518. Collapse removed the command field from the interactive controls; expand restored it. Pial stayed selected and the stream stayed Connected / Live.

## Risks and Follow-ups

The open card narrows the brain. ADR-0019 stays Proposed until the owner accepts it.

## Human Review

The owner requested this placement on 2026-11-17. This record does not mark ADR-0019 Accepted.
