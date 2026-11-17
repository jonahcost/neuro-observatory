# ADR-0019: Assistant card to the left of the live brain

- Status: Accepted
- Date: 2026-11-17
- Decision Owner: Project owner (requested on 2026-11-17; accepted on 2026-11-17)
- Related Work: `docs/work/completed/WORK-2026-11-17-assistant-card-placement.md`
- Supersedes: None. Display modes stay in the right-hand inspector from ADR-0015.

## Context

The assistant panel was rendered inside the display inspector, under the surface radios. The owner asked for that section to be its own card to the left of the live brain, and for the card to collapse and expand.

## Decision

The assistant is a sibling card in the desktop workspace, first column, spanning the brain and waveform rows. The live brain stays in the middle column. The display inspector stays in the right column. A header button collapses the card to a narrow rail and expands it again. Collapsing hides the controls; it does not close the EEG socket or drop the assistant poll.

## Alternatives Considered

- Leave the assistant inside the display inspector. Rejected: the owner asked for a separate card on the left.
- Place the card only beside the brain row and let the waveform run underneath it. Rejected: the findings list needs the taller column, matching the inspector.

## Consequences

The brain column is narrower while the card is open. Collapsing returns that width. Display radios, the waveform dock, and the single EEG socket are unchanged.

## Validation and Rollback

Desktop tests check that the assistant region precedes the cortical anatomy region and that collapse hides the command field. Removing the left-column card and passing the panel back into the inspector restores the previous layout.
