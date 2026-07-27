# AI Generation Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show safe reasons when generated candidates are filtered and create the first validation run before a teacher opens the review page.

**Architecture:** Keep provider output filtering in `services/generation.py`, where the exact invariant is known. Return only stable rejection codes through the generation job API. Add one API-private coordinator that validates newly persisted drafts through the existing budget-aware validator; both create and regenerate routes call it.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, Vue 3/Nuxt, Vitest.

## Global Constraints

- Never persist or expose an invalid candidate's prompt, explanation, rule JSON, or raw model output.
- Preserve existing provider failures, review state transitions, CSRF, idempotency, and acceptance gates.
- Create validation runs only for drafts generated in the current job; do not create teacher revisions.
- Use the existing `run_budget_aware_candidate_verification` implementation and `HttpGraderClient`.
- Do not address the unconfirmed G8/G1 selection observation in this slice.

---

### Task 1: Record safe candidate-filter diagnostics

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/generation.py:386-428`
- Test: `apps/api/tests/test_generation_service.py`

**Interfaces:**
- Consumes: `GeneratedCandidate`, `GenerationPlanItem`, and `GenerationAttempt.response_summary`.
- Produces: `response_summary["candidate_rejections"]` as `list[dict[str, int | str]]` with `ordinal` and `code`; `GenerationJob.failure_code == "candidate_validation_failed"` when every returned candidate is rejected by platform invariants.

- [ ] **Step 1: Write failing service tests**

```python
def test_generation_records_safe_reason_when_candidate_misses_plan_identity(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    invalid = valid_single_candidate(revision).model_copy(
        update={"candidates": [
            valid_single_candidate(revision).candidates[0].model_copy(
                update={"objective_revision_id": uuid4(), "prompt": "private invalid prompt"}
            )
        ]}
    )

    run_generation_job(session, job=job, provider=CapturingProvider(invalid))

    assert job.status is GenerationJobStatus.FAILED
    assert job.failure_code == "candidate_validation_failed"
    assert job.attempts[0].response_summary == {
        "candidate_count": 1,
        "candidate_rejections": [{"ordinal": 1, "code": "objective_revision_mismatch"}],
    }
    assert "private invalid prompt" not in str(job.attempts[0].response_summary)
```

Add parameterized equivalents for a wrong `question_type`, difficulty outside `_TARGET_DIFFICULTY_TOLERANCE`, invalid `rule_json`, and a candidate beyond the planned ordinal.

- [ ] **Step 2: Run the new test to verify it fails**

Run: `python -m pytest apps/api/tests/test_generation_service.py -k candidate_rejections -q`
Expected: FAIL because the attempt summary has only `candidate_count` and the job failure code is `None`.

- [ ] **Step 3: Implement the minimal classifier and persistence**

```python
def _candidate_rejection_code(
    *, candidate: GeneratedCandidate, plan_item: GenerationPlanItem | None, job: GenerationJob
) -> str | None:
    if plan_item is None:
        return "unexpected_candidate_ordinal"
    if candidate.objective_revision_id != job.curriculum_objective_revision_id:
        return "objective_revision_mismatch"
    if candidate.question_type != plan_item.question_type:
        return "question_type_mismatch"
    if abs(Decimal(str(candidate.difficulty)) - Decimal(str(plan_item.target_difficulty))) > Decimal(str(_TARGET_DIFFICULTY_TOLERANCE)):
        return "difficulty_out_of_tolerance"
    if validate_policy(candidate.question_type, candidate.policy_version, candidate.rule_json):
        return "policy_rule_invalid"
    return None
```

Refactor `_persist_valid_candidates` to return both the valid count and the safe rejection records, write the latter into the attempt response summary, and set `job.failure_code` to `candidate_validation_failed` only when a provider returned candidates but none survived filtering.

- [ ] **Step 4: Run service tests to verify green**

Run: `python -m pytest apps/api/tests/test_generation_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit the isolated service change**

```bash
git add apps/api/src/edu_grader_api/services/generation.py apps/api/tests/test_generation_service.py
git commit -m "fix: record generated candidate rejection reasons"
```

### Task 2: Expose a safe job failure summary

**Files:**
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_generation.py:890-904`
- Test: `apps/api/tests/test_ai_question_generation_api.py`
- Modify: `apps/web/app/lib/teacher-ai-review.ts:18-30`
- Modify: `apps/web/app/components/teacher/TeacherAiJobList.vue:16-22`
- Test: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes: `GenerationJob.failure_code` and latest `GenerationAttempt.response_summary`.
- Produces: `_job_payload(job)["failure_summary"]` as `list[str]`; frontend `TeacherAiGenerationJob.failure_summary?: string[]`.

- [ ] **Step 1: Write failing API and rendering tests**

```python
def test_list_jobs_exposes_only_safe_candidate_validation_summary(client: TestClient, session: Session) -> None:
    teacher, job = failed_job_with_response_summary(
        session,
        summary={"candidate_count": 1, "candidate_rejections": [
            {"ordinal": 1, "code": "policy_rule_invalid"}
        ]},
    )
    response = client.get("/v1/ai-question-generation/jobs", headers=authorize(client, teacher))

    item = next(item for item in response.json()["items"] if item["id"] == str(job.id))
    assert item["failure_code"] == "candidate_validation_failed"
    assert item["failure_summary"] == ["policy_rule_invalid"]
```

```ts
it('shows a failed batch reason without exposing candidate content', async () => {
  render(TeacherAiJobList, {
    props: { jobs: [{ id: 'job-1', subject: 'english', status: 'failed', failed_count: 1, failure_summary: ['policy_rule_invalid'] }] },
  })
  expect(screen.getByText('原因：评分规则不符合平台要求')).toBeTruthy()
})
```

- [ ] **Step 2: Run each new test to verify red**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py -k failure_summary -q`
Expected: FAIL because `failure_summary` is absent.

Run: `npm test -- --run apps/web/tests/teacher-ai-review-rendering.test.ts -t "failed batch reason"`
Expected: FAIL because the job type and component do not expose the summary.

- [ ] **Step 3: Implement safe projection and Chinese labels**

Add a router-private extractor that accepts only `candidate_rejections` records with an allowlisted code, deduplicates in first-seen order, and returns no more than the five stable codes. Add `failure_summary` to `_job_payload`, the web job type, and a label map in `TeacherAiJobList.vue` that renders `原因：…` only for failed jobs with a nonempty summary.

- [ ] **Step 4: Run API and web tests to verify green**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py -k failure_summary -q`
Expected: PASS.

Run: `npm test -- --run apps/web/tests/teacher-ai-review-rendering.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit the safe API/UI projection**

```bash
git add apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/tests/test_ai_question_generation_api.py apps/web/app/lib/teacher-ai-review.ts apps/web/app/components/teacher/TeacherAiJobList.vue apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: show safe AI generation failure summaries"
```

### Task 3: Run initial validation for generated drafts

**Files:**
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_generation.py:131-181, 360-414`
- Test: `apps/api/tests/test_ai_question_generation_api.py`

**Interfaces:**
- Consumes: `GenerationJob.drafts`, `GeneratedQuestionDraft.current_revision`, `HttpGraderClient`, and `run_budget_aware_candidate_verification`.
- Produces: exactly one `GenerationValidationRun` per newly persisted draft current revision, before the route commits.

- [ ] **Step 1: Write failing creation and regeneration tests**

```python
def test_created_job_has_initial_validation_run(client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher, revision = teacher_and_objective(session)
    monkeypatch.setattr(generation_router, "HttpGraderClient", DeterministicM2Client)
    response = client.post("/v1/ai-question-generation/jobs", headers=authorize(client, teacher) | {"Idempotency-Key": "initial-validation"}, json={
        "curriculum_objective_revision_id": str(revision.id),
        "items": [{"question_type": "M1", "difficulty_band": "standard"}],
        "requested_count": 1,
    })

    draft_id = client.get(f"/v1/ai-question-generation/jobs/{response.json()['id']}/questions", headers=authorize(client, teacher)).json()["items"][0]["id"]
    runs = client.get(f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=authorize(client, teacher))
    assert [item["revision_number"] for item in runs.json()["items"]] == [1]
```

Add the corresponding regeneration test and assert the validation client is not called when the job has no drafts.

- [ ] **Step 2: Run the new tests to verify red**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py -k initial_validation -q`
Expected: FAIL because a newly generated draft has no validation runs.

- [ ] **Step 3: Add one shared generation-validation coordinator**

```python
def _validate_generated_drafts(session: Session, *, job: GenerationJob) -> None:
    grader_client = HttpGraderClient(settings.grader_base_url)
    for draft in job.drafts:
        revision = draft.current_revision
        existing = session.scalar(
            select(GenerationValidationRun).where(
                GenerationValidationRun.generated_question_draft_id == draft.id,
                GenerationValidationRun.draft_revision_id == revision.id,
            )
        )
        if existing is None:
            run_budget_aware_candidate_verification(
                session, draft=draft, revision=revision, grader_client=grader_client
            )
```

Call it immediately after `run_generation_job` only when the current request reserved a new job, in both the create and regenerate routes. Import the existing validator; do not call `create_review_revision`, so no teacher revision/audit event is fabricated.

- [ ] **Step 4: Run API tests to verify green**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py -k "initial_validation or regenerate" -q`
Expected: PASS.

- [ ] **Step 5: Commit the initial-validation change**

```bash
git add apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/tests/test_ai_question_generation_api.py
git commit -m "fix: validate AI candidates when generated"
```

### Task 4: Verify the complete slice

**Files:**
- Verify only: all files from Tasks 1–3.

- [ ] **Step 1: Run focused API regressions**

Run: `python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -q`
Expected: PASS.

- [ ] **Step 2: Run the web review regression suite**

Run: `npm test -- --run apps/web/tests/teacher-ai-review-rendering.test.ts`
Expected: PASS.

- [ ] **Step 3: Run static checks**

Run: `python -m ruff check apps/api/src apps/api/tests`
Expected: PASS.

Run: `npm run lint --prefix apps/web`
Expected: PASS.

- [ ] **Step 4: Inspect final change scope**

Run: `git status --short && git diff main...HEAD --check`
Expected: only the documented API, service, and web changes; no whitespace errors.
