# Structured AI Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build governed, de-identified AI candidate-question generation with fake and OpenAI Responses providers.

**Architecture:** Core API owns authorization, job persistence, quotas, audit, and HTTP routes. `services/generator` owns a provider-neutral structured candidate contract, provider adapters, bounded retry, and schema validation; it cannot publish questions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, OpenAI Python SDK, `processor-policy`, pytest, Ruff.

## Global Constraints

- Generator receives no student, class, identity, credential, answer, or unrestricted prompt data.
- `OPENAI_API_KEY` is secret-only; `GENERATOR_OPENAI_MODEL` must be explicitly configured and recorded per attempt.
- Provider output is strict platform JSON; draft rows never publish `QuestionVersion`.
- Core question/grading services do not import OpenAI SDKs or Provider-specific types.
- Enforce per-tenant/teacher limits, idempotency, cancellation, and bounded retry.

---

### Task 1: Persist jobs, attempts, and drafts

**Files:**
- Create: `apps/api/alembic/versions/0015_ai_generation_jobs.py`
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/tests/test_generation_models.py`

**Interfaces:** Produces `GenerationJobStatus`, `GenerationJob`, `GeneratedQuestionDraft`, and `GenerationAttempt` for all subsequent tasks.

- [x] **Step 1: Write failing lifecycle/uniqueness tests**

```python
def test_generation_job_is_unique_per_tenant_idempotency_key(session):
    first = GenerationJob(tenant_id=tenant.id, teacher_user_id=user.id, idempotency_key="a" * 32, status=GenerationJobStatus.QUEUED, requested_count=1)
    second = GenerationJob(tenant_id=tenant.id, teacher_user_id=user.id, idempotency_key="a" * 32, status=GenerationJobStatus.QUEUED, requested_count=1)
    session.add_all([first, second])
    with pytest.raises(IntegrityError): session.commit()
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest apps/api/tests/test_generation_models.py -q`  
Expected: FAIL because generation models and migration head do not exist.

- [x] **Step 3: Implement schema and migration**

Create rows with tenant/teacher/profile/objective revision IDs, status, counts, bounded costs/timings, request/content hashes, policy/model/prompt version, sanitized failure code, and JSON draft payload. Add unique `(tenant_id, idempotency_key)`, draft content-hash index, and foreign keys; none point to `QuestionVersion` publication fields.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest apps/api/tests/test_generation_models.py -q`  
Expected: PASS.

- [x] **Step 5: Commit**

Run: `git add apps/api/alembic/versions/0015_ai_generation_jobs.py apps/api/src/edu_grader_api/models.py apps/api/tests/test_generation_models.py && git commit -m "feat: persist ai generation jobs"`

### Task 2: Implement provider-neutral contracts and fake provider

**Files:**
- Create: `services/generator/pyproject.toml`
- Create: `services/generator/src/edu_generator/contracts.py`
- Create: `services/generator/src/edu_generator/providers.py`
- Create: `services/generator/tests/test_contracts.py`

**Interfaces:** Produces `GenerationRequest`, `GeneratedCandidateEnvelope`, `GenerationProvider`, `FakeGenerationProvider`, and `ProviderFailure` consumed by the orchestration service.

- [x] **Step 1: Write failing strict-schema/fake determinism tests**

```python
def test_fake_provider_returns_stable_m1_m2_e1_e4_envelopes():
    result = FakeGenerationProvider(seed=7).generate(request_for("M1", "M2", "E1", "E4"))
    assert [item.question_type for item in result.candidates] == ["M1", "M2", "E1", "E4"]
    assert GeneratedCandidateEnvelope.model_validate(result.model_dump()).candidates == result.candidates
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest services/generator/tests/test_contracts.py -q`  
Expected: FAIL because generator package is absent.

- [x] **Step 3: Implement exact provider contract**

```python
class GenerationProvider(Protocol):
    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope: ...

class GeneratedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_revision_id: UUID
    question_type: Literal["M1", "M2", "E1", "E2", "E3", "E4"]
    policy_version: str
    prompt: str = Field(min_length=1, max_length=10_000)
    rule_json: dict[str, object]
    explanation: str = Field(min_length=1, max_length=4_000)
    knowledge_point: str = Field(min_length=1, max_length=200)
    difficulty: float = Field(ge=0, le=1)
```

Validate de-identification with `assert_deidentified_payload()`, reject unknown fields and oversize lists/strings, and make fake results deterministic by seed.

- [x] **Step 4: Verify GREEN and policy compatibility**

Run: `python -m pytest services/generator/tests/test_contracts.py packages/processor-policy/tests/test_processor_policy.py -q`  
Expected: PASS.

- [x] **Step 5: Commit**

Run: `git add services/generator packages/processor-policy && git commit -m "feat: add structured generation provider contract"`

### Task 3: Add OpenAI Responses adapter and controlled orchestration

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/src/edu_grader_api/settings.py`
- Create: `services/generator/src/edu_generator/openai_provider.py`
- Create: `apps/api/src/edu_grader_api/services/generation.py`
- Create: `apps/api/tests/test_generation_service.py`

**Interfaces:** Consumes Task 1 rows and Task 2 provider contract; produces `create_or_get_job()`, `run_generation_job()`, and `cancel_generation_job()`.

- [x] **Step 1: Write failing idempotency, retry, and de-identification tests**

```python
def test_timeout_retries_once_then_records_partial_failure(session, fake_provider):
    job = create_or_get_job(session, request=request, actor=teacher)
    fake_provider.failures = [ProviderTimeout(), valid_single_candidate()]
    run_generation_job(session, job=job, provider=fake_provider)
    assert job.status is GenerationJobStatus.PARTIALLY_FAILED
    assert len(job.attempts) == 2
    assert all("student_id" not in attempt.request_summary for attempt in job.attempts)
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest apps/api/tests/test_generation_service.py -q`  
Expected: FAIL because orchestration functions do not exist.

- [x] **Step 3: Implement bounded orchestration and OpenAI adapter**

Use `assert_allowed_processor_url()` before creating the OpenAI client. Require `OPENAI_API_KEY` and an explicit `GENERATOR_OPENAI_MODEL`; place the provider's JSON Schema in the Responses structured-output configuration. Convert only the validated structured response into `GeneratedCandidateEnvelope`. Catch only classified timeout/rate-limit/transient errors, retry at most two attempts, and persist sanitized digests/metrics rather than raw responses.

- [x] **Step 4: Verify GREEN and structural boundary**

Run: `python -m pytest apps/api/tests/test_generation_service.py -q`  
Expected: PASS.

Run: `rg -n "openai|OpenAI" apps/api/src/edu_grader_api/services/questions.py apps/api/src/edu_grader_api/services/grader.py`  
Expected: no matches.

- [x] **Step 5: Commit**

Run: `git add apps/api services/generator && git commit -m "feat: orchestrate governed ai generation"`

### Task 4: Expose guarded API and optional integration gate

**Files:**
- Create: `apps/api/src/edu_grader_api/routers/ai_question_generation.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Create: `apps/api/tests/test_ai_question_generation_api.py`
- Create: `apps/api/tests/test_openai_generation_integration.py`
- Modify: `.env.example`, `README.md`

**Interfaces:** Produces the issue's job/status/questions/regenerate/cancel endpoints, paginated responses, stable error codes, and an opt-in OpenAI integration test.

- [x] **Step 1: Write failing API tests**

```python
def test_teacher_job_request_is_idempotent_and_never_publishes(client):
    first = client.post("/v1/ai-question-generation/jobs", json=request, headers=teacher_headers)
    second = client.post("/v1/ai-question-generation/jobs", json=request, headers=teacher_headers)
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"/v1/ai-question-generation/jobs/{first.json()['id']}/questions", headers=teacher_headers).json()["items"][0]["teacher_state"] == "pending_review"
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py -q`  
Expected: FAIL with route not found.

- [x] **Step 3: Implement routes and documentation**

Guard all routes with the teacher/admin authorization model, tenant filters, count caps, cancellation state checks, page limits, and audit events. Mark the real OpenAI integration test with `skipif` unless API key, model snapshot, and allowlisted host are configured; it must generate one schema-valid candidate without printing requests/responses or secrets.

- [x] **Step 4: Run verification**

Run: `make api-lint && make api-test && make test`  
Expected: all checks PASS; integration test is skipped without controlled configuration.

- [ ] **Step 5: Commit**

Run: `git add apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/src/edu_grader_api/main.py apps/api/tests .env.example README.md && git commit -m "feat: expose governed ai generation api"`

## Plan Self-Review

- Task 1 covers governed persistence and idempotency; Task 2 covers strict provider-neutral structured output; Task 3 covers OpenAI secret/allowlist/retry isolation; Task 4 covers API, audit, quotas, integration gating, and full verification.
- Every task begins with a failing test and ends with a focused commit. Model, Provider, and Core boundaries are introduced before consumption.
