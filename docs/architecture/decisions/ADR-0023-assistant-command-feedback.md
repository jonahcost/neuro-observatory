# ADR-0023: Show assistant command feedback, and do not seek from a question

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner (this record stays Proposed until the owner marks it Accepted)
- Related Work: `docs/work/completed/WORK-2026-11-17-assistant-command-feedback.md`
- Supersedes: None. The closed lexicon in ADR-0016 still owns explicit commands such as “show me that segment.”

## Context

Sending “Explain Fp1 and Fp2 to me” left the command in the field and showed no waiting state. The model then proposed `seek_to_finding`. On the live synthetic stream the server answered that the stream cannot jump backward, which is not a reply to the question.

## Decision

1. Send clears the command immediately, shows “Asking the local model…”, and then replaces that line with the result.
2. A model proposal of seek, marker, baseline lock, or display mode is declined unless the typed text already matched that lexicon command. A channel highlight is kept only when the typed text names those channels.

## Alternatives Considered

- Leave the field filled until the model returns. Rejected: a multi-second local completion looks like a failed send.
- Accept every schema-valid model intent. Rejected: a question was executed as a seek.

## Consequences

An explanation question gets a clarification instead of moving the stream. Explicit lexicon commands are unchanged.

## Validation and Rollback

A desktop test covers the cleared field and the reply. An engine test covers a model seek proposal for this question. Restoring the old submit handler and executing model action intents returns the previous behavior.
