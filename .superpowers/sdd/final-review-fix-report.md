# Final review fixes

## Scope

Implemented all three Important final-review findings in the teacher AI review UI only. No backend routes, request payloads, CSRF handling, idempotency behavior, route guards, or bulk request atomicity were changed.

## TDD evidence

### Red

Added focused rendering regressions before production edits, then ran:

```text
npm test -- tests/teacher-ai-review-rendering.test.ts
```

The test run failed as expected (4 failed / 43 passed):

- The blocked-decision test could not find `data-testid="blocked-primary-action"`.
- Accepted and rejected terminal-state tests could not find `题型：E4` in the technical disclosure.
- The same-revision replacement warning-run regression found the bulk button enabled (`expected undefined to be defined` for its `disabled` attribute), proving that acknowledgement was incorrectly retained.

One copy assertion was deliberately corrected during the green cycle to match the final teacher-facing wording; no production behavior was added before the red failures were observed.

### Green

After the implementation, the focused rendering suite passed:

```text
Test Files  1 passed (1)
Tests       47 passed (47)
```

The required focused regression set also passed:

```text
npm test -- tests/teacher-ai-review-rendering.test.ts tests/teacher-ai-review.test.ts tests/teacher-ai-review-presentation.test.ts
Test Files  3 passed (3)
Tests       60 passed (60)
```

The Chromium end-to-end check passed:

```text
npx playwright test e2e/teacher-ai-review.spec.ts --project=chromium
2 passed (26.6s)
```

## Changes

### 1. Warning acknowledgement now has validation-run identity

`TeacherAiReviewWorkspace.vue` stores `validationRunId` alongside the selected draft revision and status. During refresh/pruning, a warning acknowledgement is retained only when the draft revision, warning status, and validation run ID all still match the authoritative validation summary.

The regression selects and acknowledges warning run A, replaces it with warning run B at the same revision, refreshes through route navigation, and confirms that bulk accept is disabled until acknowledgement is renewed. Blocked selection removal, selection revision checks, CSRF acquisition, idempotency-key reuse, and the single atomic bulk request path remain unchanged.

### 2. Blocked decision action is visible and editing explains revalidation

`TeacherAiCandidateReview.vue` now renders the blocked presentation's `primaryAction` as clear next-step guidance. The edit disclosure is labeled `修改题目并重新校验`, explicitly says saving triggers validation again, and keeps the existing `save-revision` test ID, event handler, and save payload while changing its visible label to `保存并重新校验`.

### 3. Terminal audit context remains visible

The always-available advanced technical disclosure now displays immutable candidate audit fields: question type, objective revision ID, and policy version. Editing controls remain pending-review-only, and terminal accepted/rejected behavior still hides all write controls while retaining the existing question-bank draft notice and link.

## Files changed

- `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- `apps/web/tests/teacher-ai-review-rendering.test.ts`
