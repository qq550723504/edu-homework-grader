# Final review fix report

Date: 2026-07-23

## Scope and root causes

This pass addresses the three final-review findings without changing the provider output schema, client ownership of `target_difficulty`, or any docs/plan file.

1. `TeacherAiReviewWorkspace.vue` kept each draft's regeneration idempotency key indefinitely. A successful regeneration followed by returning to the source draft therefore replayed the original job. The workspace now clears the draft key after a confirmed success or an HTTP/local rejection, and retains it only when the outcome is unknown (including a network failure).
2. `generator-v1` did not explicitly bind provider candidates one-to-one to the ordered generation plan. The historical v1 template remains byte-for-byte unchanged. A new immutable `generator-v2` uses the same `generated_question_candidates-v1` schema and requires exactly one candidate per ordered input item, in the same order and with the same question type and requested target difficulty. New server-owned job snapshots now default to v2; persisted v1 jobs remain resolvable.
3. The generation form rendered internal difficulty IDs as public labels. It now displays `基础` / `标准` / `提高` while retaining `foundation` / `standard` / `stretch` in counts, request values, and test IDs.

## TDD evidence

- RED backend:
  `python -m pytest` for the new v2 template contract, outbound OpenAI plan/instructions, and service/API default-version tests failed 4/4 because v2 was unavailable and new jobs still selected v1.
- RED Web:
  `npm test -- teacher-ai-review-rendering.test.ts teacher-ai-generation-rendering.test.ts` failed the successful regenerate/reselect/regenerate key regression and localized-label assertion. A separate unknown-outcome lifecycle test also failed because a confirmed HTTP rejection retained the old key.
- GREEN focused:
  the five backend contract/default-version checks passed, and the two rendering files passed 48/48 tests.

## Final verification

- `python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -q`
  - 103 passed.
- `cd apps/web && npm test -- teacher-ai-generation.test.ts teacher-ai-generation-rendering.test.ts teacher-ai-review.test.ts teacher-ai-review-rendering.test.ts`
  - 4 files, 60 tests passed.
- `cd apps/web && npm run build`
  - Production build completed successfully. Existing sourcemap, chunk-size, and dependency deprecation warnings remain non-failing.
- `python -m ruff check ...`
  - All modified Python files passed.
- `python -m ruff format --check ...`
  - All modified Python files were already formatted after the formatting pass.
- `git diff --check`
  - Passed.

## Files changed

- `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- `apps/web/app/components/teacher/TeacherAiGenerationForm.vue`
- `apps/web/tests/teacher-ai-review-rendering.test.ts`
- `apps/web/tests/teacher-ai-generation-rendering.test.ts`
- `services/generator/src/edu_generator/prompt_templates.py`
- `services/generator/tests/test_contracts.py`
- `apps/api/src/edu_grader_api/services/generation.py`
- `apps/api/tests/test_generation_service.py`
- `apps/api/tests/test_ai_question_generation_api.py`
- `.superpowers/sdd/final-fix-report.md`
