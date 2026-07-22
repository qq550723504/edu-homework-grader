# Final review fix report

Date: 2026-07-22

## Scope

This fix addresses only the three Important findings in `final-review.md`.

1. `accepted` and `rejected` drafts are now terminal/read-only in `TeacherAiCandidateReview.vue`. All editable controls and save/reject/accept actions are disabled, each action handler refuses terminal writes, and `TeacherAiReviewWorkspace.vue` independently enforces `teacher_state === 'pending_review'` before allocating an idempotency key or calling an API.
2. Rejection detail is shown only for `reason === 'other'`. The client trims it, rejects blank/whitespace content, rejects more than 500 characters with a specific local message, and emits no request on validation failure. A reachable backend `rejection_detail_required` error now maps to the owned detail message instead of the generic 409 state-conflict message.
3. Acceptance retains `accepted_question_version_id` by draft and revision, renders “已创建题库草稿” plus the exact `QuestionVersion` identifier, and links to the existing `/teacher#questions` question-bank workspace. The accepted identity is available immediately from the decision and remains available after the draft refresh.

The optional Minor findings were intentionally left out to keep the correction narrowly scoped.

## Regression evidence

- Red: `cd apps/web && npm test -- --run tests/teacher-ai-review-rendering.test.ts` initially failed 9 new/updated assertions for terminal-state writes, `other` detail validation, accepted identity handoff, and owned server-error mapping.
- Green: the same focused DOM/workspace suite passed: 1 file, 30 tests.
- Targeted Web: `cd apps/web && npm test -- --run tests/teacher-ai-review.test.ts tests/teacher-ai-review-rendering.test.ts tests/teacher-workbench.test.ts` passed: 3 files, 48 tests.
- Full Web: `cd apps/web && npm test` passed: 16 files, 90 tests.
- Production build: `cd apps/web && npm run build` passed. The existing module-preload sourcemap, large chunk, and dependency deprecation warnings remain non-failing.
- Backend contract regression: `$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src'; python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py -q` passed: 37 tests.

## Files changed

- `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- `apps/web/tests/teacher-ai-review-rendering.test.ts`
- `.superpowers/sdd/final-fix-report.md`
