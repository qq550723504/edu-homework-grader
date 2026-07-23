# AI Question Workbench Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete GitHub #41 with server-owned per-candidate difficulty plans, browser single-candidate regeneration, and atomic batch acceptance.

**Architecture:** Persist an ordered plan in existing GenerationJob.distribution_json. It is the source of truth for each ordinal's type, band, and target. The API derives targets from curriculum bounds, sends them through the Provider contract, and preserves the source plan item during regeneration. Vue only constructs requests and coordinates state; authorization, validation, quota, idempotency, and draft-only publication remain server-owned.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLAlchemy, Vue 3/Nuxt 4, TypeScript, Vitest, Playwright.

## Global Constraints

- foundation, standard, and stretch are the only public difficulty bands.
- Derive target_difficulty only from active curriculum bounds; never accept it from the browser.
- Use existing GenerationJob.distribution_json; add neither table nor migration.
- Preserve authorization, CSRF, idempotency, quota, de-identification, immutable snapshots, and public-error boundaries.
- Blocked candidates are never acceptable; warnings require per-item confirmation; batch acceptance remains all-or-nothing and creates draft QuestionVersions only.
- Never expose Provider keys, prompts, private validation features, student data, tokens, or speculative cost figures.

---

## File Structure

| File | Responsibility |
| --- | --- |
| services/generator/src/edu_generator/contracts.py | Typed Provider plan input. |
| services/generator/src/edu_generator/providers.py | Fake Provider obeys each requested target. |
| apps/api/src/edu_grader_api/services/generation.py | Derives/persists plans, validates outputs, inherits plan on regeneration. |
| apps/api/src/edu_grader_api/routers/ai_question_generation.py | Narrow public bodies and safe routing. |
| apps/api/tests/test_generation_service.py | Plan, Provider, persistence, and regeneration coverage. |
| apps/api/tests/test_ai_question_generation_api.py | HTTP validation and idempotency coverage. |
| apps/web/app/lib/teacher-ai-generation.ts | Plan-count expansion and create request types. |
| apps/web/app/components/teacher/TeacherAiGenerationForm.vue | Type by band form controls. |
| apps/web/app/lib/teacher-ai-review.ts | Regenerate and bulk-accept clients. |
| apps/web/app/components/teacher/TeacherAiCandidateReview.vue | Candidate regeneration action. |
| apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue | Batch selection, warning confirmation, and refresh. |
| apps/web/tests/teacher-ai-*.test.ts | Unit and DOM tests. |
| apps/web/e2e/teacher-ai-*.spec.ts | G7/G8 browser evidence. |

## Task 1: Add the ordered Provider plan contract

**Files:**

- Modify: services/generator/src/edu_generator/contracts.py
- Modify: services/generator/src/edu_generator/providers.py
- Modify: services/generator/src/edu_generator/openai_provider.py
- Modify: apps/api/src/edu_grader_api/services/generation.py
- Modify: apps/api/tests/test_generation_service.py
- Modify: services/generator/tests/test_contracts.py
- Modify: apps/api/tests/test_openai_generation_integration.py

**Interfaces:**

- Consumes: GeneratedCandidate.difficulty.
- Produces: GenerationPlanItem(question_type, difficulty_band, target_difficulty) and GenerationRequest.items.
- Transitional boundary: adapt old persisted distribution_json.question_types into standard-band midpoint items inside the service until Task 2 persists complete items; do not retain a public question_types field.

- [ ] **Step 1: Write the failing test**

Add this test to apps/api/tests/test_generation_service.py:

~~~python
def test_fake_provider_preserves_ordered_generation_plan() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(), objective_text="Add within 100.",
        difficulty_min=0, difficulty_max=1, grade="G7", subject="mathematics",
        items=[
            GenerationPlanItem(question_type="M1", difficulty_band="foundation", target_difficulty=0.2),
            GenerationPlanItem(question_type="M2", difficulty_band="stretch", target_difficulty=0.8),
        ],
        requested_count=2, policy_version="2026.07", prompt_version="generator-v1",
    )
    result = FakeGenerationProvider(seed=7).generate(request)
    assert [item.question_type for item in result.candidates] == ["M1", "M2"]
    assert [item.difficulty for item in result.candidates] == [0.2, 0.8]
~~~

- [ ] **Step 2: Run it to verify it fails**

Run: python -m pytest apps/api/tests/test_generation_service.py -k ordered_generation_plan -v

Expected: FAIL because GenerationPlanItem and GenerationRequest.items do not exist.

- [ ] **Step 3: Implement the minimal shared contract**

In contracts.py, add:

~~~python
DifficultyBand = Literal["foundation", "standard", "stretch"]

class GenerationPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType
    difficulty_band: DifficultyBand
    target_difficulty: float = Field(ge=0, le=1)
~~~

Replace GenerationRequest.question_types with items: list[GenerationPlanItem] = Field(min_length=1, max_length=20). Add an after validator requiring len(items) == requested_count. Update template lookups to use a list of item.question_type. In FakeGenerationProvider.generate, enumerate items, emit item.question_type, and assign difficulty=item.target_difficulty.

- [ ] **Step 4: Verify the slice**

Run: python -m pytest apps/api/tests/test_generation_service.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/providers.py apps/api/tests/test_generation_service.py
git commit -m "feat: add ordered AI generation plan contract"
~~~

## Task 2: Persist and enforce server-owned difficulty plans

**Files:**

- Modify: apps/api/src/edu_grader_api/services/generation.py
- Modify: apps/api/src/edu_grader_api/routers/ai_question_generation.py
- Modify: apps/api/src/edu_grader_api/e2e_support.py
- Modify: apps/api/tests/test_generation_service.py
- Modify: apps/api/tests/test_ai_question_generation_api.py
- Modify: apps/api/tests/test_generation_models.py

**Interfaces:**

- Consumes: GenerationPlanItem from Task 1 and curriculum difficulty_min/difficulty_max.
- Produces: GenerationJobRequest.items, derive_generation_plan(revision, items), and distribution_json with items.
- Migration boundary: migrate in-repository E2E/model fixtures to complete items; production deliberately rejects incomplete historical question_types JSON rather than restoring compatibility or adding a migration.

- [ ] **Step 1: Write failing service and API tests**

Add tests proving a request with foundation and stretch items persists:

~~~python
assert job.distribution_json["items"] == [
    {"question_type": "M1", "difficulty_band": "foundation", "target_difficulty": 0.2},
    {"question_type": "M1", "difficulty_band": "stretch", "target_difficulty": 0.8},
]
~~~

Add an HTTP test that an item containing target_difficulty returns 422 because the public Pydantic body forbids extras. Add a regeneration test where ordinal two has a distinct band and assert its new single-item job copies ordinal two's complete persisted item and original grade/subject/policy/prompt snapshot.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -k "difficulty_plan or regeneration_inherits" -v

Expected: FAIL because create bodies still use question_types, jobs persist only types, and regeneration cannot select a source plan item.

- [ ] **Step 3: Implement the smallest service/API change**

Define public CreateGenerationPlanItemRequest with only question_type and difficulty_band. Expose CreateGenerationJobRequest.items instead of question_types. Add:

~~~python
_DIFFICULTY_BAND_FRACTIONS = {"foundation": 0.2, "standard": 0.5, "stretch": 0.8}

def derive_generation_plan(revision, items):
    return [
        GenerationPlanItem(
            question_type=item.question_type,
            difficulty_band=item.difficulty_band,
            target_difficulty=round(
                revision.difficulty_min
                + (revision.difficulty_max - revision.difficulty_min)
                * _DIFFICULTY_BAND_FRACTIONS[item.difficulty_band],
                4,
            ),
        )
        for item in items
    ]
~~~

Validate allowed types before persisting an items array. Make _provider_request decode only this shape. In _persist_valid_candidates, compare each returned ordinal against its plan item for objective, type, and a documented target-difficulty tolerance; discard mismatches.

For regeneration, read the source draft ordinal from the source job plan and create a one-item request from that exact item with existing GenerationJobSnapshot.from_job(original). Never update source draft, revision, or decision rows.

- [ ] **Step 4: Verify the API/service slice**

Run: python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add apps/api/src/edu_grader_api/services/generation.py apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py
git commit -m "feat: enforce AI generation difficulty plans"
~~~

## Task 3: Add type by difficulty-band generation controls

**Files:**

- Modify: apps/web/app/lib/teacher-ai-generation.ts
- Modify: apps/web/app/components/teacher/TeacherAiGenerationForm.vue
- Modify: apps/web/tests/teacher-ai-generation.test.ts
- Modify: apps/web/tests/teacher-ai-generation-rendering.test.ts

**Interfaces:**

- Consumes: API items containing question_type and difficulty_band.
- Produces: TeacherAiGenerationPlanItem and expandGenerationPlanCounts.

- [ ] **Step 1: Write failing pure and DOM tests**

Add:

~~~ts
expect(expandGenerationPlanCounts({ M1: { foundation: 1, standard: 0, stretch: 1 } })).toEqual([
  { question_type: 'M1', difficulty_band: 'foundation' },
  { question_type: 'M1', difficulty_band: 'stretch' },
])
~~~

Then use question-type-M1-foundation-increment in the mounted form and assert createAiGenerationJob receives items containing the one M1 foundation item, not question_types.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: cd apps/web; npm test -- teacher-ai-generation.test.ts teacher-ai-generation-rendering.test.ts

Expected: FAIL because type by band state and public request items do not exist.

- [ ] **Step 3: Implement the smallest accessible change**

Export:

~~~ts
export const teacherAiDifficultyBands = ['foundation', 'standard', 'stretch'] as const
export type TeacherAiDifficultyBand = typeof teacherAiDifficultyBands[number]
export interface TeacherAiGenerationPlanItem {
  question_type: TeacherAiQuestionType
  difficulty_band: TeacherAiDifficultyBand
}
~~~

Store nested counts by type and band; flatten deterministically by teacherAiQuestionTypes then teacherAiDifficultyBands. Render three labelled increment/decrement pairs under each allowed type. Use test IDs built from type, band, and action. Reset nested counts on every parent curriculum change and retain the total quota cap. Submit only objective revision, items, requested count, and optional de-identified constraint.

- [ ] **Step 4: Verify the form**

Run: cd apps/web; npm test -- teacher-ai-generation.test.ts teacher-ai-generation-rendering.test.ts; npm run build

Expected: PASS and build exits 0.

- [ ] **Step 5: Commit**

~~~powershell
git add apps/web/app/lib/teacher-ai-generation.ts apps/web/app/components/teacher/TeacherAiGenerationForm.vue apps/web/tests/teacher-ai-generation.test.ts apps/web/tests/teacher-ai-generation-rendering.test.ts
git commit -m "feat: select AI generation difficulty bands"
~~~

## Task 4: Connect browser regeneration and atomic batch acceptance

**Files:**

- Modify: apps/web/app/lib/teacher-ai-review.ts
- Modify: apps/web/app/components/teacher/TeacherAiCandidateReview.vue
- Modify: apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue
- Modify: apps/web/tests/teacher-ai-review.test.ts
- Modify: apps/web/tests/teacher-ai-review-rendering.test.ts

**Interfaces:**

- Consumes: existing regenerate and bulk-accept API endpoints.
- Produces: regenerateAiCandidate, bulkAcceptAiCandidates, selected IDs, and a regenerated-job route.

- [ ] **Step 1: Write failing client and DOM tests**

Assert this exact bulk request:

~~~ts
await bulkAcceptAiCandidates(request, 'csrf-token', 'job-1', 'key-1', [{
  draft_id: 'draft-1', expected_revision_number: 2, confirm_warnings: true,
}])
expect(request).toHaveBeenCalledWith('/api/core/v1/ai-question-generation/jobs/job-1/bulk-accept', {
  method: 'POST',
  headers: { 'X-CSRF-Token': 'csrf-token', 'Idempotency-Key': 'key-1' },
  body: { items: [{ draft_id: 'draft-1', expected_revision_number: 2, confirm_warnings: true }] },
})
~~~

Add DOM cases showing blocked drafts cannot be selected, a warning needs its own acknowledgement, accepted state changes only after a successful response, and regeneration routes to the new job.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: cd apps/web; npm test -- teacher-ai-review.test.ts teacher-ai-review-rendering.test.ts

Expected: FAIL because clients and controls are absent.

- [ ] **Step 3: Implement narrow clients and workspace coordination**

Add regenerateAiCandidate(request, csrfToken, draftId, key) and bulkAcceptAiCandidates(request, csrfToken, jobId, key, items). Keep selected IDs and warning acknowledgements keyed by draft.id; clear them when a selected job changes or a refresh reports a terminal state. Derive one idempotency key from unchanged selection/revision/confirmation intent, disable concurrent writes, patch only returned decisions, then refresh from the server. Reuse existing retry-refresh handling when the response succeeds but refresh is uncertain.

Expose a regenerate event only for pending_review candidates. The workspace obtains CSRF, retains a per-draft key, calls the helper, and navigates to the returned job. Reuse public 401/403, 409, 422, 429, 503, and network messages; never render server text.

- [ ] **Step 4: Verify the review UI**

Run: cd apps/web; npm test -- teacher-ai-review.test.ts teacher-ai-review-rendering.test.ts; npm run build

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add apps/web/app/lib/teacher-ai-review.ts apps/web/app/components/teacher/TeacherAiCandidateReview.vue apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/tests/teacher-ai-review.test.ts apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: complete AI candidate batch review"
~~~

## Task 5: Prove #41 browser workflows and record delivery

**Files:**

- Modify: apps/api/src/edu_grader_api/e2e_support.py
- Modify: apps/web/e2e/teacher-ai-generation.spec.ts
- Modify: apps/web/e2e/teacher-ai-review.spec.ts
- Modify: docs/ai-question-generation-plan.md

**Interfaces:**

- Consumes: all interfaces from Tasks 1–4.
- Produces: deterministic G7/G8 browser evidence and a current issue-status record.

- [ ] **Step 1: Write failing E2E assertions**

Seed a de-identified G7 M1/M2 job with one passed and one warning candidate, plus a G8 E1/E4 job. Assert batch selection, explicit warning confirmation, and success text. Assert regeneration navigates to a different job. Assert resulting QuestionVersions are draft only, blocked candidates create no version, and G8 regeneration retains source type and difficulty plan.

- [ ] **Step 2: Run E2E tests to verify they fail**

Run: cd apps/web; npm run test:e2e -- --grep "batch acceptance|single regeneration"

Expected: FAIL because fixtures and UI controls do not exist.

- [ ] **Step 3: Implement deterministic fixtures and project-status update**

Seed only de-identified curriculum, teacher, job, draft, validation, and review-policy data in e2e_support.py. Add stable test IDs for selection, warning confirmation, batch submit, and regeneration. Update docs/ai-question-generation-plan.md to mark #41 delivered while leaving #42, #43, and #31 open.

- [ ] **Step 4: Run full verification**

Run:

~~~powershell
make api-lint
make api-test
make web-test
make web-build
make web-e2e
git diff --check HEAD~4..HEAD
~~~

Expected: lint/build exit 0; API/Web suites pass; runtime and Chromium E2E pass; diff check is clean.

- [ ] **Step 5: Commit**

~~~powershell
git add apps/api/src/edu_grader_api/e2e_support.py apps/web/e2e/teacher-ai-generation.spec.ts apps/web/e2e/teacher-ai-review.spec.ts docs/ai-question-generation-plan.md
git commit -m "test: verify AI workbench completion"
~~~

## Final Requirement Checklist

- [ ] Teacher selects curriculum objective, type mix, count, and foundation/standard/stretch distribution.
- [ ] Jobs persist an immutable server-derived ordered plan and Providers receive it.
- [ ] Teacher regenerates one pending candidate without mutating source audit history.
- [ ] Teacher atomically accepts selected eligible candidates; blocked items remain ineligible and warnings are individually confirmed.
- [ ] Accepted candidates create draft QuestionVersions only; server checks authorization, CSRF, quota, de-identification, validation, and idempotency.
- [ ] G7 M1/M2 and G8 E1/E4 browser flows prove the vertical slice.
- [ ] Documentation distinguishes delivered #41 scope from #42/#43/#31 work.
