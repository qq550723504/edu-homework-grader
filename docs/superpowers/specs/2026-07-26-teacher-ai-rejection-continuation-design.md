# Teacher AI Rejection Continuation Flow Design

**Goal:** A teacher who rejects an AI-generated candidate can immediately continue the review workflow without changing the rejected audit record.

## Problem

`GeneratedQuestionDraft.teacher_state = rejected` is correctly terminal for the original candidate. The review UI also treats it as terminal, but it currently hides every next action. In a one-question batch, the teacher is left on a read-only screen. In a multi-question batch, the teacher must manually discover another candidate in the side list.

The existing regeneration endpoint authorizes the teacher and creates a new one-item generation job from the original plan item. It does not require the source draft to remain in `pending_review`. The frontend adds the incorrect `pending_review` restriction before calling that endpoint.

## Chosen Design

### Rejected candidate remains immutable

The original rejected candidate continues to show its rejection status and audit information. It never regains edit, accept, batch-accept, or reject controls. No backend state transition changes.

### Explicit continuation actions

The rejected-state action area presents:

1. **重新生成同题型候选题** — the primary action. It invokes the existing regeneration endpoint with the rejected draft ID and its existing idempotency behavior. The endpoint creates a new one-item job and the workspace navigates to that job. The source rejected record remains unchanged.
2. **继续审核下一题** — shown only when the current batch has another `pending_review` draft. It changes only the route selection to the next pending candidate in ordinal order, wrapping to the first pending candidate when necessary. It does not make an API write.
3. **生成新批次** — shown when no pending candidate remains in the current batch. It links to the existing new-generation page so a teacher can change the generation plan rather than being forced to regenerate the rejected plan item.

The candidate component renders the contextual actions and emits an intent event for moving to the next candidate. The workspace owns ordering and route navigation because it owns the batch draft list.

## Boundaries

- Reuse the existing `regenerateAiCandidate` client function and `POST /ai-generated-questions/{draft_id}/regenerate` endpoint; do not add a second rejection-specific API.
- Keep server-side rejection and access controls unchanged.
- Do not automatically navigate away from the rejected record: the teacher receives a visible acknowledgement and chooses the next action.
- Do not expose a continuation action for accepted candidates; their existing question-bank link remains the next step.

## Verification

1. Component tests prove a rejected candidate exposes regeneration, conditionally exposes the next-review action, and still hides all mutable original-candidate controls.
2. Workspace tests prove regeneration is allowed for a rejected selected draft, and next-review navigation selects the ordered pending draft without an API write.
3. Browser coverage proves `拒绝 -> 重新生成` creates a new job while the original draft remains rejected, and `拒绝 -> 继续审核下一题` selects the next pending candidate.
4. Run the full frontend suite, E2E API supervisor tests, browser review scenarios, and production build.
