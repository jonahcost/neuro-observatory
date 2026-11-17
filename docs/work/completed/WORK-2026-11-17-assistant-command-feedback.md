# WORK-2026-11-17-assistant-command-feedback: Show the assistant reply and decline an unasked seek

- Status: Completed
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0023-assistant-command-feedback.md`

## Objective

Make a sent assistant command visible immediately, and stop a free-form question from being executed as a seek.

## Scope

In scope: the command form in `AssistantPanel`, and the model-proposal guard in `AssistantService`.

Non-goals: teaching the model electrode anatomy, and changing lexicon commands.

## Acceptance Criteria

- [x] Send clears the command and shows a waiting line, then the result.
- [x] A model `seek_to_finding` proposal for “Explain Fp1 and Fp2 to me” does not use the synthetic-stream seek refusal.

## Implementation Summary

Send clears the field, disables itself, and shows “Asking the local model…” until the result replaces that line under the form. A model proposal to seek, mark, lock the baseline, or change the display is declined when the typed text did not match that command.

## Validation Evidence

- Posted the same question to the running engine before the fix. It returned HTTP 200 in about 7 seconds with “That segment is not open for replay. The live synthetic stream cannot jump backward.” The form never cleared that text.
- `cd services/neuro-engine && uv run pytest tests/test_assistant_commands.py -q --tb=short` — 8 passed.
- `cd services/neuro-engine && uv run ruff check src/neuro_engine/assistant/service.py tests/test_assistant_commands.py` — all checks passed.
- `yarn nx run desktop:test -- src/assistant/AssistantPanel.spec.tsx src/app/app.spec.tsx` — 6 passed.

## Risks and Follow-ups

ADR-0023 stays Proposed until the owner accepts it. The local model still cannot give a textbook explanation of electrode names; it can clarify or cite a finding.

## Human Review

The owner reported this on 2026-11-17. This record does not mark ADR-0023 Accepted.
