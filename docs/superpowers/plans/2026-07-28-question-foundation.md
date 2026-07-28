# Question Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every `QuestionVersion` a versioned local rich-content snapshot plus immutable media and external-license metadata without breaking existing M1/M2/E1–E4 behaviour.

**Architecture:** Keep `prompt`, `reading_material` and `rule_json` as the current grading and compatibility projection. Add `content_schema_version` and `content_json` to `QuestionVersion`; add child rows for media and external source/license snapshots. A pure content module validates and converts the legacy projection, services own lifecycle copying, and a teacher-only endpoint exposes safe metadata while student assignment responses remain unchanged.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, pytest.

## Global Constraints

- Do not add a QTI runtime, Provider SDK, media uploader, new frontend editor, search, Paper/Blueprint or export feature.
- Do not store binary media, public/signed URLs, access tokens, provider temporary URLs, prompt payload logs or student data.
- Existing M1/M2/E1–E4 `prompt`, `reading_material`, `rule_json`, fingerprints, grading, publication and assignment responses remain compatible.
- Published `QuestionVersion` records and their license/source snapshots are immutable; a change creates a successor draft and independent child rows.
- Student responses never expose external IDs, license JSON or media storage keys.

---

### Task 1: Define and test the `question-content-v1` compatibility contract

**Files:**
- Create: `apps/api/src/edu_grader_api/services/question_content.py`
- Create: `apps/api/tests/test_question_content.py`

**Interfaces:**
- Produces `QUESTION_CONTENT_SCHEMA_VERSION = "question-content-v1"`.
- Produces `legacy_question_content(prompt: str, reading_material: str | None) -> dict[str, object]`.
- Produces `validate_question_content(content: object) -> dict[str, object]` and `legacy_projection(content: Mapping[str, object]) -> tuple[str, str | None]`.
- Raises `QuestionContentValidationError(code: str)` with only stable codes: `question_content_invalid`, `question_content_legacy_mismatch`, `question_content_unsafe_metadata`.

- [ ] **Step 1: Write the failing contract tests**

```python
from edu_grader_api.services.question_content import (
    legacy_projection,
    legacy_question_content,
    validate_question_content,
)

def test_legacy_content_round_trips_prompt_and_reading_material() -> None:
    content = legacy_question_content("What is 2 + 2?", "Read this first.")
    assert content["stem"] == [{"kind": "text", "text": "What is 2 + 2?"}]
    assert legacy_projection(content) == ("What is 2 + 2?", "Read this first.")

def test_content_rejects_unknown_blocks_and_unsafe_metadata() -> None:
    with pytest.raises(QuestionContentValidationError, match="question_content_invalid"):
        validate_question_content({"stem": [{"kind": "html", "html": "<script>"}]})
    with pytest.raises(QuestionContentValidationError, match="question_content_unsafe_metadata"):
        validate_question_content({"stem": [], "metadata": {"url": "https://example.test"}})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_question_content.py -v` from `apps/api`.

Expected: FAIL because `question_content` does not exist.

- [ ] **Step 3: Implement the minimal pure contract**

```python
QUESTION_CONTENT_SCHEMA_VERSION = "question-content-v1"

def legacy_question_content(prompt: str, reading_material: str | None) -> dict[str, object]:
    return {
        "stem": [{"kind": "text", "text": prompt}],
        "reading_material": [] if reading_material is None else [{"kind": "text", "text": reading_material}],
        "response": {"kind": "legacy-rule"},
        "explanation": [],
        "metadata": {"grade": None, "difficulty": None, "estimated_minutes": None},
    }
```

Accept only `text` blocks in `stem`, `reading_material` and `explanation`; require a `legacy-rule` response; reject extra top-level keys and recursively reject keys containing `url`, `token`, `secret`, `cookie` or `authorization`. Normalize empty reading material to `None` in `legacy_projection`.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_question_content.py -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/services/question_content.py apps/api/tests/test_question_content.py
git commit -m "feat: define question content contract"
```

### Task 2: Persist content, media metadata and immutable source-license snapshots

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0026_question_content_snapshots.py`
- Modify: `apps/api/tests/test_question_models.py`

**Interfaces:**
- `QuestionVersion.content_schema_version: str` and `QuestionVersion.content_json: dict[str, object]` are non-null after migration.
- `QuestionMediaAsset(question_version_id, kind, storage_key, mime_type, byte_size, content_hash, alt_text, position)`.
- `ExternalContentReference(question_version_id, provider, external_id, source_version, content_hash, license_code, license_snapshot_json, tenant_scope_id, allow_persist, allow_student_display, allow_ai_processing, allow_redistribution, contract_expires_at)`.

- [ ] **Step 1: Write failing model and migration tests**

```python
def test_question_version_has_versioned_content_snapshot() -> None:
    assert QuestionVersion.__table__.c.content_schema_version.nullable is False
    assert QuestionVersion.__table__.c.content_json.nullable is False

def test_external_reference_is_unique_per_version_and_provider_identity() -> None:
    assert any(
        constraint.name == "uq_external_content_reference_identity"
        for constraint in ExternalContentReference.__table__.constraints
    )
```

Extend the migration isolation test to assert addition of both `question_versions` columns and creation/removal of `question_media_assets` and `external_content_references`.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_question_models.py -v`.

Expected: FAIL because the new models and migration are absent.

- [ ] **Step 3: Add model and Alembic migration**

Use JSON with the PostgreSQL JSONB variant, UUID foreign keys and `(question_version_id, position)` uniqueness for media. Give `ExternalContentReference` a unique `(question_version_id, provider, external_id, source_version)` constraint and indexes on `question_version_id` and `provider`.

Migration order:

```python
op.add_column("question_versions", sa.Column("content_schema_version", sa.String(40), nullable=True))
op.add_column("question_versions", sa.Column("content_json", sa.JSON(), nullable=True))
# stream existing rows; use legacy_question_content(prompt, reading_material)
# then alter both columns nullable=False and create child tables
```

Keep the migration self-contained: duplicate the small legacy projection helper in the migration rather than importing runtime application code. The downgrade drops child tables before the two columns.

- [ ] **Step 4: Run focused model and migration tests**

Run: `python -m pytest tests/test_question_models.py -v`.

Expected: PASS with existing fingerprint/index tests still passing.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0026_question_content_snapshots.py apps/api/tests/test_question_models.py
git commit -m "feat: persist question content snapshots"
```

### Task 3: Keep creation, edits and successor drafts consistent

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/questions.py`
- Modify: `apps/api/src/edu_grader_api/services/ai_question_review.py`
- Create: `apps/api/tests/test_question_content_lifecycle.py`

**Interfaces:**
- Extend `create_question(..., content_json: dict[str, object] | None = None) -> QuestionVersion`.
- Extend `update_draft(..., content_json: dict[str, object] | None = None) -> None`.
- Add `copy_question_content_snapshot(session, source: QuestionVersion, target: QuestionVersion) -> None`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_create_question_derives_content_from_legacy_fields(session, teacher) -> None:
    version = create_question(..., prompt="Calculate 2 + 2", reading_material=None, ...)
    assert version.content_schema_version == "question-content-v1"
    assert legacy_projection(version.content_json) == (version.prompt, None)

def test_successor_copies_independent_source_and_media_rows(session, published_version, teacher) -> None:
    successor = create_successor_draft(session, published_version, actor_user_id=teacher.id)
    assert successor.content_json == published_version.content_json
    assert successor.content_json is not published_version.content_json
    assert successor.external_content_references[0].id != published_version.external_content_references[0].id
```

Also cover rejecting explicit content whose text does not match `prompt`/`reading_material`, rejecting `allow_persist=False` or `allow_student_display=False` references on a publishable draft, and preserving the existing AI acceptance flow.

- [ ] **Step 2: Run the lifecycle tests to verify they fail**

Run: `python -m pytest tests/test_question_content_lifecycle.py tests/test_ai_question_review.py -v`.

Expected: FAIL because lifecycle code does not create or copy snapshots.

- [ ] **Step 3: Implement lifecycle synchronization**

On create and AI acceptance, derive `content_json` when omitted; when provided, call `legacy_projection` and reject a mismatch before persisting. On draft edit, update both the legacy projection and `content_json` in the same transaction. On successor creation, deep-copy JSON and create new child records; do not reuse primary keys. Reject direct lifecycle mutation when status is `published` using the existing `QuestionVersionStateError` boundary.

- [ ] **Step 4: Run focused lifecycle regression tests**

Run: `python -m pytest tests/test_question_content_lifecycle.py tests/test_questions.py tests/test_ai_question_review.py -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/services/questions.py apps/api/src/edu_grader_api/services/ai_question_review.py apps/api/tests/test_question_content_lifecycle.py
git commit -m "feat: preserve question content across versions"
```

### Task 4: Expose a teacher-only safe content view without changing student payloads

**Files:**
- Modify: `apps/api/src/edu_grader_api/routers/questions.py`
- Modify: `apps/api/tests/test_questions.py`
- Modify: `apps/api/tests/test_assignments.py`

**Interfaces:**
- Add `GET /v1/question-versions/{version_id}/content` requiring `Role.TEACHER` and tenant ownership.
- Response includes `content_schema_version`, `content`, ordered media metadata without `storage_key`, and source metadata without `external_id` or `license_snapshot_json`.

- [ ] **Step 1: Write failing route and non-disclosure tests**

```python
def test_teacher_can_read_safe_content_snapshot(client, teacher_headers, version) -> None:
    body = client.get(f"/v1/question-versions/{version.id}/content", headers=teacher_headers).json()
    assert body["content_schema_version"] == "question-content-v1"
    assert "storage_key" not in body["media"][0]
    assert "external_id" not in body["sources"][0]
    assert "license_snapshot_json" not in body["sources"][0]

def test_student_assignment_detail_keeps_existing_question_projection(...) -> None:
    assert "content" not in item
    assert "sources" not in item
```

- [ ] **Step 2: Run the route tests to verify they fail**

Run: `python -m pytest tests/test_questions.py tests/test_assignments.py -v`.

Expected: FAIL with a missing route or unexpected payload assertion.

- [ ] **Step 3: Implement the safe response projection**

Use `_tenant_version` for tenant isolation. Return only `kind`, `mime_type`, `byte_size`, `content_hash`, `alt_text` and `position` for media; return only `provider`, `source_version`, `content_hash`, `license_code`, four use flags and `contract_expires_at` for sources. Do not modify `routers/assignments.py` response construction beyond tests proving it remains unchanged.

- [ ] **Step 4: Run route and assignment regression tests**

Run: `python -m pytest tests/test_questions.py tests/test_assignments.py -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/routers/questions.py apps/api/tests/test_questions.py apps/api/tests/test_assignments.py
git commit -m "feat: expose safe question content metadata"
```

### Task 5: Run the full relevant verification suite

**Files:**
- Modify only if a verification failure identifies a defect in Tasks 1–4.

- [ ] **Step 1: Run API question, assignment and generation-review suites**

Run: `python -m pytest tests/test_question_content.py tests/test_question_content_lifecycle.py tests/test_question_models.py tests/test_questions.py tests/test_assignments.py tests/test_ai_question_review.py -v` from `apps/api`.

Expected: PASS.

- [ ] **Step 2: Run migration and formatting checks**

Run: `python -m alembic upgrade head` and `ruff check src tests` from `apps/api`.

Expected: migration succeeds; Ruff reports no errors.

- [ ] **Step 3: Run frontend contract regression**

Run: `npm test -- tests/assignment-composition.test.ts` from `apps/web`.

Expected: PASS; no frontend payload rewrite is required.

- [ ] **Step 4: Inspect final scope**

Run: `git diff origin/main...HEAD --check` and `git status --short`.

Expected: no whitespace errors and only #155 files changed.

## Plan self-review

- Spec coverage: Task 1 implements the versioned, safe content contract; Task 2 persists content, media and license snapshots; Task 3 makes lifecycle copies immutable and compatible; Task 4 enforces teacher-only safe projection; Task 5 verifies migrations and existing behaviour.
- Placeholder scan: no TBD/TODO markers or undefined interfaces remain.
- Type consistency: all later tasks consume `content_schema_version`, `content_json` and `legacy_projection` defined in Tasks 1–2.
