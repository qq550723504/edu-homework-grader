# 教师 AI 候选题审核基础 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让教师以不可变修订和验证门禁，安全地拒绝或接受 AI 候选题为现有题库草稿。

**Architecture:** Provider 原稿留在 `GeneratedQuestionDraft`。候选修订和审核决定均是 append-only 记录；验证运行绑定修订，接受事务只能使用当前修订的最近合格验证运行，并创建既有 `QuestionVersion(draft)`。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、Pytest、SQLite 测试数据库。

## Global Constraints

- 原始候选、验证运行和审核决定不得编辑或删除。
- 教师只可访问自己创建的任务；管理员只限本租户。
- `blocked` 不可接受，`warning` 要 `confirm_warnings=true`，任何接受结果均为题库 `draft`。
- 所有写操作使用当前 `revision_number` 进行乐观并发检查，冲突码是 `review_revision_conflict`。
- 响应和审计元数据不得包含系统 Prompt、教师约束、Provider 密钥或内部诊断。

---

### Task 1: 持久化不可变修订、验证快照和审核决定

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py:683-789`
- Create: `apps/api/alembic/versions/0017_ai_generated_question_reviews.py`
- Modify: `apps/api/src/edu_grader_api/services/generation.py:250-278`
- Test: `apps/api/tests/test_generation_models.py`

**Interfaces:** Produces `GeneratedQuestionDraftRevision`, `GeneratedQuestionReviewDecision`, `GeneratedQuestionDraft.current_revision_id`, and `GenerationValidationRun.draft_revision_id`. Write-side revision and decision rows carry idempotency key plus request digest.

- [ ] **Step 1: Write failing model tests**

```python
def test_generated_draft_creates_an_immutable_initial_review_revision(session: Session) -> None:
    draft = persist_generated_draft(session)
    assert draft.current_revision.revision_number == 1
    assert draft.current_revision.candidate_json == draft.candidate_json
    assert draft.current_revision.content_hash == draft.content_hash

def test_validation_run_references_the_review_revision(session: Session) -> None:
    run = persist_validation_run(session)
    assert run.draft_revision_id == run.draft.current_revision_id
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/test_generation_models.py -q`

Expected: missing revision model or relationship.

- [ ] **Step 3: Implement models and portable migration**

Create `generated_question_draft_revisions` with unique `(generated_question_draft_id, revision_number)`, immutable JSON candidate, content hash, editor, timestamp, optional idempotency key and request digest; a unique `(generated_question_draft_id, idempotency_key)` index permits initial rows with `NULL` but prevents duplicate edits. Create append-only `generated_question_review_decisions` with action, reason, warning confirmation, actor, accepted `question_version_id`, idempotency key, request digest and timestamp; make `(generated_question_draft_id, action, idempotency_key)` unique. The Alembic migration must add nullable foreign keys first, backfill each old draft with revision 1 using Python `uuid4()`, attach old validation runs to it, then make the references non-null. Change generation persistence so every new candidate flushes then appends revision 1 in the same transaction.

- [ ] **Step 4: Verify Task 1**

Run:

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest apps/api/tests/test_generation_models.py -q
ruff check apps/api/src/edu_grader_api/models.py apps/api/src/edu_grader_api/services/generation.py apps/api/alembic/versions/0017_ai_generated_question_reviews.py apps/api/tests/test_generation_models.py
ruff format --check apps/api/src/edu_grader_api/models.py apps/api/src/edu_grader_api/services/generation.py apps/api/alembic/versions/0017_ai_generated_question_reviews.py apps/api/tests/test_generation_models.py
```

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/models.py apps/api/src/edu_grader_api/services/generation.py apps/api/alembic/versions/0017_ai_generated_question_reviews.py apps/api/tests/test_generation_models.py
git commit -m "feat: persist AI candidate review revisions"
```

### Task 2: 将验证严格绑定到候选修订

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/question_verification.py:135-180,1300-1365,1627-1685`
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_validation.py:27-96`
- Test: `apps/api/tests/test_question_verification.py`
- Test: `apps/api/tests/test_ai_question_generation_api.py`

**Interfaces:** `run_candidate_verification(session, draft, revision, grader_client)` persists `draft_revision_id`; route payloads include only `revision_number`.

- [ ] **Step 1: Write failing revision-validation tests**

```python
def test_validation_uses_selected_revision_not_provider_original(session: Session) -> None:
    draft, revision = create_edited_revision(session, prompt="What is 9 + 9?")
    run = run_candidate_verification(session, draft=draft, revision=revision, grader_client=client)
    assert run.draft_revision_id == revision.id

def test_old_validation_run_is_not_current_after_edit(client: TestClient) -> None:
    assert latest_validation_payload(client, draft_id)["revision_number"] == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py -q`

Expected: verifier has no revision argument and payload lacks revision number.

- [ ] **Step 3: Implement snapshot-bound verification**

Replace direct candidate reads with `revision.candidate_json`; calculate fingerprints from the revision snapshot; persist `draft_revision_id`. Same-batch duplicate detection must join every peer draft's current revision instead of provider originals. Retain the row lock and fail closed if the locked revision/hash differs from the evaluated snapshot. Existing runs remain readable but can never be selected as the current revision's result.

- [ ] **Step 4: Verify Task 2**

Run:

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py -q
ruff check apps/api/src/edu_grader_api/services/question_verification.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py
ruff format --check apps/api/src/edu_grader_api/services/question_verification.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py
```

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py
git commit -m "feat: bind candidate validation to review revisions"
```

### Task 3: 实现审核服务及受控题库草稿入库

**Files:**
- Create: `apps/api/src/edu_grader_api/services/ai_question_review.py`
- Modify: `apps/api/src/edu_grader_api/services/questions.py`
- Test: `apps/api/tests/test_ai_question_review.py`

**Interfaces:**
- `create_review_revision(session, draft, actor, expected_revision_number, candidate, grader_client)`
- `reject_review_draft(session, draft, actor, expected_revision_number, reason, detail)`
- `accept_review_draft(session, draft, actor, expected_revision_number, confirm_warnings)`

- [ ] **Step 1: Write failing state-machine tests**

```python
def test_blocked_revision_cannot_be_accepted(session: Session) -> None:
    with pytest.raises(ReviewStateError, match="validation_blocked"):
        accept_review_draft(session, draft, actor, 1, confirm_warnings=False)

def test_warning_confirmation_creates_exactly_one_draft(session: Session) -> None:
    decision = accept_review_draft(session, draft, actor, 1, confirm_warnings=True)
    assert decision.question_version.status is VersionStatus.DRAFT

def test_stale_revision_never_overwrites_newer_edit(session: Session) -> None:
    with pytest.raises(ReviewConflictError, match="review_revision_conflict"):
        create_review_revision(session, draft, actor, expected_revision_number=1, candidate=payload)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/test_ai_question_review.py -q`

Expected: review service does not exist.

- [ ] **Step 3: Implement append-only review service**

Validate user edits with `GeneratedCandidate.model_validate`; reject changed objective revision, type or policy version before appending revision `N + 1`, then synchronously run Task 2 verification. Reject only with the fixed reasons `incorrect_answer`, `out_of_scope`, `unclear_wording`, `duplicate`, `unsuitable_for_students`, `other`; `other` needs 1–500 characters. Accept locks draft, current revision and latest run, rejects missing/stale/blocked results, requires warning confirmation, invokes existing `create_question`, and creates title `AI {question_type} candidate {ordinal}`. Persist the decision, source version and audit event in the same transaction; never publish or create test results.

- [ ] **Step 4: Verify Task 3**

Run:

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest apps/api/tests/test_ai_question_review.py apps/api/tests/test_questions_api.py apps/api/tests/test_question_verification.py -q
ruff check apps/api/src/edu_grader_api/services/ai_question_review.py apps/api/src/edu_grader_api/services/questions.py apps/api/tests/test_ai_question_review.py
ruff format --check apps/api/src/edu_grader_api/services/ai_question_review.py apps/api/src/edu_grader_api/services/questions.py apps/api/tests/test_ai_question_review.py
```

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/services/ai_question_review.py apps/api/src/edu_grader_api/services/questions.py apps/api/tests/test_ai_question_review.py
git commit -m "feat: review AI candidates into question drafts"
```

### Task 4: 暴露审核 API 并收紧任务授权

**Files:**
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_generation.py:28-306`
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_validation.py:27-119`
- Test: `apps/api/tests/test_ai_question_generation_api.py`

**Interfaces:** `GET /v1/ai-question-generation/jobs`; `POST /v1/ai-generated-questions/{draft_id}/revisions`; `POST /v1/ai-generated-questions/{draft_id}/reject`; `POST /v1/ai-generated-questions/{draft_id}/accept`.

- [ ] **Step 1: Write failing authorization and API tests**

```python
def test_teacher_lists_and_mutates_only_own_generation_jobs(client: TestClient) -> None:
    assert client.get("/v1/ai-question-generation/jobs", headers=other_teacher_headers).json()["items"] == []
    assert client.post(f"/v1/ai-generated-questions/{draft_id}/reject", headers=other_teacher_headers, json=payload).status_code == 404

def test_accept_api_returns_draft_version_and_requires_current_validation(client: TestClient) -> None:
    response = client.post(f"/v1/ai-generated-questions/{draft_id}/accept", headers=headers, json={"expected_revision_number": 1, "confirm_warnings": False})
    assert response.json()["detail"]["code"] == "validation_blocked"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py -q`

Expected: absent routes or tenant-wide authorization.

- [ ] **Step 3: Implement route request models and safe projections**

Centralize `_authorized_job` and `_authorized_draft`: teachers filter `GenerationJob.teacher_user_id == actor.id`; admins retain tenant scope. Require `Idempotency-Key` for revision/reject/accept, digest the request and replay only the exact same action to prevent double clicks from creating another revision or draft. Return revision number, latest run summary and accepted version ID; omit hashes, provider request summaries and exception details.

- [ ] **Step 4: Verify Task 4**

Run:

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_question_validation_models.py -q
ruff check apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_ai_question_generation_api.py
ruff format --check apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_ai_question_generation_api.py
```

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_ai_question_generation_api.py
git commit -m "feat: expose AI candidate review APIs"
```

### Task 5: 文档、全量验证和 PR 准备

**Files:**
- Modify: `docs/superpowers/specs/2026-07-22-teacher-ai-review-foundation-design.md`
- Modify: `docs/superpowers/plans/2026-07-22-teacher-ai-review-foundation.md`

- [ ] **Step 1: 回填实际验证和范围边界**

Record the exact tests, migration result, authorization checks and the intentionally remaining Nuxt/bulk work. Do not close #41 yet.

- [ ] **Step 2: Run final verification**

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest apps/api/tests/test_generation_models.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_questions_api.py apps/api/tests/test_question_validation_models.py -q
ruff check apps/api/src/edu_grader_api apps/api/tests/test_generation_models.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_questions_api.py apps/api/tests/test_question_validation_models.py
ruff format --check apps/api/src/edu_grader_api apps/api/tests/test_generation_models.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_questions_api.py apps/api/tests/test_question_validation_models.py
git diff --check origin/main...HEAD
```

- [ ] **Step 3: Commit documentation**

```powershell
git add docs/superpowers/specs/2026-07-22-teacher-ai-review-foundation-design.md docs/superpowers/plans/2026-07-22-teacher-ai-review-foundation.md
git commit -m "docs: record AI candidate review delivery"
```
