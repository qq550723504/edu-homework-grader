# Question Versions and Grading Policies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Implement Issue #3 with immutable question versions, platform-owned grading policies, version-bound test cases, persisted test runs, and publication gates.

**Architecture:** SQLAlchemy models add question and rule version persistence to the existing tenant boundary. A policy registry validates rule JSON through jsonschema Draft 2020-12. A focused service owns version transitions, test-case validation, Grader calls, and audit writes; FastAPI routes only translate HTTP input and authorization.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, jsonschema, httpx, pytest, PostgreSQL.

## Global Constraints

- Every question, version, policy reference, test case, and run is tenant-scoped through its parent question.
- A published or archived question version is never updated; modification creates a successor draft.
- Rules and test answers are JSON validated before persistence; teachers cannot supply a schema.
- Publish succeeds only after the latest completed full run for the exact draft version passes all required categories.
- Grader requests contain no user, tenant, school ID, token, or other personal data.
- Ownership or tenant boundary failures return 404; invalid JSON shape returns 422; invalid publish state returns 409.
- Every behavior change is test-first and every state transition writes an audit event.

---

## File structure

| File | Responsibility |
| --- | --- |
| apps/api/src/edu_grader_api/models.py | Question, version, policy, test-case, run, and run-case ORM mappings. |
| apps/api/alembic/versions/0002_question_versions.py | Persistent schema upgrade and downgrade. |
| apps/api/src/edu_grader_api/policies.py | Built-in policy schemas, Draft202012Validator, and normalized validation errors. |
| apps/api/src/edu_grader_api/services/questions.py | Version creation, test-case checks, test execution, publish gate, audit records. |
| apps/api/src/edu_grader_api/routers/questions.py | Teacher question authoring, test-run, and publish routes. |
| apps/api/src/edu_grader_api/settings.py | Grader base URL and request timeout configuration. |
| apps/api/tests/test_question_models.py | Immutability, unique version, and policy reference tests. |
| apps/api/tests/test_policies.py | JSON Schema validation and JSON-path error tests. |
| apps/api/tests/test_questions.py | Authorization, test-run persistence, and publish gating routes. |

### Task 1: Persist question versions and policy registry

**Files:**
- Modify: apps/api/pyproject.toml, apps/api/src/edu_grader_api/models.py
- Create: apps/api/alembic/versions/0002_question_versions.py
- Test: apps/api/tests/test_question_models.py

**Interfaces:**
- Produces Question, QuestionVersion, GradingPolicy, QuestionTestCase, QuestionTestRun, and QuestionTestCaseRun.
- QuestionVersion.status is draft, published, or archived; QuestionTestRun.status is passed, failed, or grading_error.

- [ ] **Step 1: Write failing model tests**

~~~
def test_question_versions_are_unique_and_published_versions_are_immutable(session):
    question, draft = make_question_with_draft(session)
    published = publish_version(session, draft)
    with pytest.raises(ImmutableVersionError):
        update_question_version(session, published.id, prompt="changed")
    with pytest.raises(IntegrityError):
        session.add(QuestionVersion(question_id=question.id, version_number=1, ...))
        session.commit()
~~~

- [ ] **Step 2: Verify red**

Run: python -m pytest apps/api/tests/test_question_models.py -q

Expected: FAIL because question-version models and transition service do not exist.

- [ ] **Step 3: Add mappings and migration**

Add jsonschema>=4.26,<5 to API dependencies. Map:
- questions with tenant_id, created_by_user_id, title, current draft/published version IDs;
- question_versions with question_id, version_number, status, prompt, question_type, grading_policy_id, rule_json, author, publication timestamps;
- grading_policies with question_type plus policy_version unique and JSON schema;
- question_test_cases with version ID, category, answer JSON, expected decision, expected score, expected evidence;
- question_test_runs and question_test_case_runs with saved Grader version, trigger, result, evidence, errors, and timestamps.

Create revision 0002_question_versions with foreign keys, tenant indexes, question/version unique constraint, and downgrade in reverse dependency order. Seed the platform policy rows through a deterministic bootstrap function, not migration-time teacher data.

- [ ] **Step 4: Verify green**

Run:

~~~
python -m pytest apps/api/tests/test_question_models.py -q
$env:DATABASE_URL = "sqlite+pysqlite:///$env:TEMP/question-version.db"
python -m alembic -c apps/api/alembic.ini upgrade head
~~~

Expected: model tests pass and the fresh database reaches 0002_question_versions.

- [ ] **Step 5: Commit**

~~~
git add apps/api
git commit -m "feat(api): add question version schema"
~~~

### Task 2: Validate platform policy instances and version transitions

**Files:**
- Create: apps/api/src/edu_grader_api/policies.py, apps/api/src/edu_grader_api/services/questions.py
- Test: apps/api/tests/test_policies.py, apps/api/tests/test_question_versions.py

**Interfaces:**
- Produces validate_policy(question_type, policy_version, rule_json) -> list[PolicyValidationError].
- Produces create_question, create_successor_draft, and replace_draft_version functions.

- [ ] **Step 1: Write failing validation tests**

~~~
def test_numeric_policy_reports_json_path_for_invalid_tolerance():
    errors = validate_policy("M1", "1", {"expected": 5, "tolerance": -1})
    assert errors == [PolicyValidationError(path="/tolerance", message="...")]
~~~

- [ ] **Step 2: Verify red**

Run: python -m pytest apps/api/tests/test_policies.py apps/api/tests/test_question_versions.py -q

Expected: FAIL because policy registry and version service do not exist.

- [ ] **Step 3: Implement schema registry and transitions**

Define built-in Draft 2020-12 schemas for M1 numeric, M2 expression, E1 exact, and E4 assisted short answer. Each schema has additionalProperties false and requires only fields understood by the matching Grader request. Sort jsonschema errors by absolute_path and return JSON Pointer paths.

create_question stores version 1 as draft. Replacing a draft creates version_number + 1 and archives the prior draft. Creating a successor from published data copies prompt, type, policy, rule JSON, and test cases into a new draft. Each transition appends question.created, question.version_created, or question.draft_superseded audit records.

- [ ] **Step 4: Verify green**

Run: python -m pytest apps/api/tests/test_policies.py apps/api/tests/test_question_versions.py -q

Expected: all policy and immutability tests pass.

- [ ] **Step 5: Commit**

~~~
git add apps/api
git commit -m "feat(api): validate versioned grading policies"
~~~

### Task 3: Run version-bound cases and enforce publication

**Files:**
- Modify: apps/api/src/edu_grader_api/settings.py, apps/api/src/edu_grader_api/services/questions.py
- Test: apps/api/tests/test_question_runs.py

**Interfaces:**
- Produces run_question_tests(session, version_id, trigger, grader_client) -> QuestionTestRun.
- Produces publish_question_version(session, actor, version_id) -> QuestionVersion.

- [ ] **Step 1: Write failing run and publish tests**

~~~
def test_publish_rejects_a_version_without_a_passing_complete_run(session, teacher, draft):
    with pytest.raises(PublishConflict):
        publish_question_version(session, teacher, draft.id)

def test_full_run_persists_each_case_and_allows_publish(session, teacher, draft, grader_client):
    add_categories(draft, "correct", "incorrect", "empty", "boundary")
    run = run_question_tests(session, draft.id, "manual", grader_client)
    assert run.status is RunStatus.PASSED
    assert publish_question_version(session, teacher, draft.id).status is VersionStatus.PUBLISHED
~~~

- [ ] **Step 2: Verify red**

Run: python -m pytest apps/api/tests/test_question_runs.py -q

Expected: FAIL because no test-run or publish service exists.

- [ ] **Step 3: Implement deterministic test execution**

Use an injected GraderClient protocol with grade(question_type, rule_json, answer_json) returning decision, score, evidence, and grader_version. Use httpx only in the production client. Save a case result for every case, including grader exceptions as grading_error. Require correct, incorrect, empty, and boundary; require invalid_ast for M2; require needs_review for E4. Publish only if the latest full run is passed, complete, and belongs to the same draft version. Append question.test_run and question.published audit records.

- [ ] **Step 4: Verify green**

Run: python -m pytest apps/api/tests/test_question_runs.py -q

Expected: passing runs persist results; failed, incomplete, stale, and Grader-error runs return PublishConflict.

- [ ] **Step 5: Commit**

~~~
git add apps/api
git commit -m "feat(api): gate question publication on test runs"
~~~

### Task 4: Expose teacher routes and complete verification

**Files:**
- Create: apps/api/src/edu_grader_api/routers/questions.py
- Modify: apps/api/src/edu_grader_api/main.py, README.md, Makefile
- Test: apps/api/tests/test_questions.py

**Interfaces:**
- POST /v1/questions, POST /v1/questions/{question_id}/versions, PUT /v1/question-versions/{version_id}
- POST /v1/question-versions/{version_id}/test-cases, POST /v1/question-versions/{version_id}/test-runs, POST /v1/question-versions/{version_id}/publish

- [ ] **Step 1: Write failing authorization and publishing-route tests**

~~~
def test_only_draft_author_can_replace_a_version(teacher_client, other_teacher_client, draft):
    assert other_teacher_client.put(f"/v1/question-versions/{draft.id}", json=payload).status_code == 404
    assert teacher_client.put(f"/v1/question-versions/{draft.id}", json=payload).status_code == 201

def test_publish_returns_409_with_failed_case_ids(teacher_client, draft):
    response = teacher_client.post(f"/v1/question-versions/{draft.id}/publish")
    assert response.status_code == 409
~~~

- [ ] **Step 2: Verify red**

Run: python -m pytest apps/api/tests/test_questions.py -q

Expected: FAIL because the question router is not registered.

- [ ] **Step 3: Implement routes and error translation**

Require Role.TEACHER for every authoring route. Scope every query by principal tenant; draft mutation additionally requires created_by_user_id. Return 422 with policy path errors, 404 for non-visible resources, and 409 with failing or missing case categories on publish. Register the router in main.py. Document the policy lifecycle, migration command, and test-run endpoint in README and add a question-test Make target.

- [ ] **Step 4: Run full verification**

Run:

~~~
python -m pytest apps/api/tests services/grader/tests -q
python -m ruff format --check apps/api services/grader
python -m ruff check apps/api services/grader
docker compose config
git diff --check
~~~

Expected: all tests, formatting, static checks, Compose validation, and whitespace checks pass.

- [ ] **Step 5: Commit**

~~~
git add apps/api README.md Makefile
git commit -m "feat(api): manage versioned questions"
~~~

