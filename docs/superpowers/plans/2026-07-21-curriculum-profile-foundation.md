# Curriculum Profile Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver #37's versioned, platform-wide curriculum catalogue, its guarded API and four-profile seed so later AI generation can cite immutable objective revisions.

**Architecture:** Keep curriculum records global and independent of tenant data. SQLAlchemy models own relational integrity; `services/curriculum.py` owns lifecycle and cross-field validation; `routers/curriculum.py` owns HTTP contracts and current-role access. Use CASE-inspired stable item codes and explicit associations, but do not implement CASE import/export in this issue.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, pytest.

## Global Constraints

- Internal levels are exactly `K3_4`, `K4_5`, `K5_6`, `G1`–`G13`; K levels only permit `learning_activity-v1`.
- `G13` is invalid without an explicit active profile; no default profile may be inferred.
- First-release curriculum administration uses existing `Role.ADMIN`; do not add a second user role.
- Curriculum rows contain no tenant, school, class, student, answer or copied source text.
- Approved objective revisions are append-only; retirement blocks new use but preserves historical IDs.
- The seed codes are `cn-preschool-3-6-2012`, `cn-compulsory-2022`, `cn-high-school-2017-2020`, and `cefr-2020`.

---

## File structure

- Modify: `apps/api/src/edu_grader_api/models.py` — curriculum enums and relational models.
- Create: `apps/api/alembic/versions/0013_curriculum_profile_foundation.py` — schema plus four-profile seed and reversible downgrade.
- Create: `apps/api/src/edu_grader_api/services/curriculum.py` — lifecycle, filtering, revision and prerequisite validation.
- Modify: `apps/api/src/edu_grader_api/dependencies.py` — teacher-or-admin reader dependency.
- Create: `apps/api/src/edu_grader_api/routers/curriculum.py` — read and `admin` write/review API contracts.
- Modify: `apps/api/src/edu_grader_api/main.py` — register the curriculum router.
- Create: `apps/api/tests/test_curriculum_models.py` — database and service unit coverage.
- Create: `apps/api/tests/test_curriculum.py` — authenticated HTTP, access and 422 coverage.
- Modify: `README.md` and `docs/ai-question-generation-plan.md` — add API and source-governance references only after endpoints exist.

### Task 1: Model the immutable curriculum catalogue

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py`
- Test: `apps/api/tests/test_curriculum_models.py`

**Interfaces:**
- Produces `CurriculumProfile`, `CurriculumGradeMapping`, `CurriculumObjective`, `CurriculumObjectiveRevision`, `CurriculumPrerequisite`, `CurriculumSourceRecord` and string enums `CurriculumProfileStatus`, `CurriculumRevisionStatus`, `CurriculumActivityType`.
- Consumed by the migration, service and router tasks.

- [ ] **Step 1: Write failing relational-integrity tests**

```python
def test_objective_revision_number_is_unique_per_objective(session: Session) -> None:
    objective = CurriculumObjective(profile=active_profile, code="MATH-G1-NUM-001", subject="mathematics", domain="number")
    session.add_all([objective, revision(objective, 1), revision(objective, 1)])
    with pytest.raises(IntegrityError):
        session.commit()

def test_prerequisite_cannot_reference_the_same_revision(session: Session) -> None:
    item = revision(active_objective, 1)
    session.add(CurriculumPrerequisite(objective_revision=item, prerequisite_revision=item))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run tests and verify the models are unavailable**

Run: `python -m pytest apps/api/tests/test_curriculum_models.py -q`

Expected: import failure for `CurriculumProfile`.

- [ ] **Step 3: Add the models and SQL constraints**

```python
class CurriculumProfile(Base):
    __tablename__ = "curriculum_profiles"
    __table_args__ = (UniqueConstraint("code", name="uq_curriculum_profiles_code"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[CurriculumProfileStatus] = mapped_column(Enum(CurriculumProfileStatus, native_enum=False, values_callable=role_values), nullable=False)
    source_record_id: Mapped[UUID] = mapped_column(ForeignKey("curriculum_source_records.id"), nullable=False)

class CurriculumObjectiveRevision(Base):
    __tablename__ = "curriculum_objective_revisions"
    __table_args__ = (UniqueConstraint("objective_id", "revision_number", name="uq_curriculum_objective_revision_number"),)
```

Use `JSON().with_variant(JSONB, "postgresql")` for `allowed_question_types`; retain a stable objective code separately from the immutable revision text. Add a check constraint on prerequisites that rejects equal revision IDs.

- [ ] **Step 4: Run focused tests and format**

Run: `python -m pytest apps/api/tests/test_curriculum_models.py -q; python -m ruff format --check apps/api; python -m ruff check apps/api`

Expected: focused tests pass and Ruff exits 0.

- [ ] **Step 5: Commit the model slice**

```powershell
git add apps/api/src/edu_grader_api/models.py apps/api/tests/test_curriculum_models.py
git commit -m "feat: add curriculum catalogue models"
```

### Task 2: Add migration and deterministic initial catalogue

**Files:**
- Create: `apps/api/alembic/versions/0013_curriculum_profile_foundation.py`
- Modify: `apps/api/tests/test_curriculum_models.py`

**Interfaces:**
- Consumes the six models from Task 1.
- Produces the `0013_curriculum_profile_foundation` Alembic head and four active source/profile rows.

- [ ] **Step 1: Write failing seed and migration tests**

```python
def test_curriculum_seed_has_all_required_profile_codes(session: Session) -> None:
    assert set(session.scalars(select(CurriculumProfile.code))) == {
        "cn-preschool-3-6-2012", "cn-compulsory-2022",
        "cn-high-school-2017-2020", "cefr-2020",
    }

def test_alembic_curriculum_upgrade_and_downgrade(tmp_path: Path) -> None:
    # Upgrade 0012 -> 0013, assert curriculum_profiles exists, downgrade to 0012, assert it does not.
```

- [ ] **Step 2: Run tests and verify they fail before the revision exists**

Run: `python -m pytest apps/api/tests/test_curriculum_models.py -q`

Expected: seed rows or Alembic revision missing.

- [ ] **Step 3: Create the reversible Alembic revision**

```python
revision = "0013_curriculum_profile_foundation"
down_revision = "0012_guardian_consent_state_integrity"

def upgrade() -> None:
    # create source, profile, mapping, objective, revision and prerequisite tables;
    # insert deterministic UUID-keyed source/profile/objective/revision seed rows.

def downgrade() -> None:
    # drop prerequisites, revisions, objectives, mappings, profiles, then sources.
```

Seed at least one short, reviewed objective for each applicable initial profile, including a K `learning_activity-v1` objective and CEFR language objective. Use only title, URL, version and source locator metadata; do not copy standard text.

- [ ] **Step 4: Run migration and focused tests**

Run: `python -m alembic -c apps/api/alembic.ini upgrade head; python -m pytest apps/api/tests/test_curriculum_models.py -q`

Expected: Alembic reaches `0013_curriculum_profile_foundation`; tests pass.

- [ ] **Step 5: Commit the migration slice**

```powershell
git add apps/api/alembic/versions/0013_curriculum_profile_foundation.py apps/api/tests/test_curriculum_models.py
git commit -m "feat: seed governed curriculum profiles"
```

### Task 3: Implement catalogue lifecycle and validation service

**Files:**
- Create: `apps/api/src/edu_grader_api/services/curriculum.py`
- Modify: `apps/api/tests/test_curriculum_models.py`

**Interfaces:**
- Produces `list_active_profiles`, `list_active_objectives`, `create_objective_revision`, `activate_objective_revision`, `retire_objective_revision`, `add_prerequisite`, and `CurriculumValidationError(code, field, message)`.
- Consumed by `routers/curriculum.py`.

- [ ] **Step 1: Write failing service tests**

```python
def test_k_revision_rejects_scored_question_types(session: Session) -> None:
    with pytest.raises(CurriculumValidationError, match="K levels only allow learning_activity-v1"):
        create_objective_revision(session, objective=k_objective, allowed_question_types=["M1"], activity_type="scored_question", actor_user_id=admin.id)

def test_retired_revision_is_not_returned_for_new_generation_selection(session: Session) -> None:
    retire_objective_revision(session, revision=active_revision, actor_user_id=admin.id)
    assert active_revision.id not in {item.id for item in list_active_objectives(session, profile_id=profile.id)}
```

- [ ] **Step 2: Run the service tests and verify failure**

Run: `python -m pytest apps/api/tests/test_curriculum_models.py -q`

Expected: import failure for `edu_grader_api.services.curriculum`.

- [ ] **Step 3: Implement lifecycle checks and audit events**

```python
def create_objective_revision(session: Session, *, objective: CurriculumObjective, revision_number: int, text: str, source_locator: str, allowed_question_types: list[str], difficulty_min: float, difficulty_max: float, activity_type: CurriculumActivityType, actor_user_id: UUID) -> CurriculumObjectiveRevision:
    _validate_revision(objective, allowed_question_types, difficulty_min, difficulty_max, activity_type)
    revision = CurriculumObjectiveRevision(..., status=CurriculumRevisionStatus.DRAFT)
    session.add(revision)
    return revision
```

Validate supported question types through `question_policy_catalog()`, detect prerequisite cycles with a traversal over active revision IDs, and append audit records using the acting admin's tenant ID with metadata restricted to IDs, codes, states and version numbers.

- [ ] **Step 4: Run focused tests and linters**

Run: `python -m pytest apps/api/tests/test_curriculum_models.py -q; python -m ruff format --check apps/api; python -m ruff check apps/api`

Expected: pass with no formatter or lint findings.

- [ ] **Step 5: Commit the service slice**

```powershell
git add apps/api/src/edu_grader_api/services/curriculum.py apps/api/tests/test_curriculum_models.py
git commit -m "feat: validate curriculum lifecycle"
```

### Task 4: Expose guarded curriculum APIs

**Files:**
- Modify: `apps/api/src/edu_grader_api/dependencies.py`
- Create: `apps/api/src/edu_grader_api/routers/curriculum.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Create: `apps/api/tests/test_curriculum.py`

**Interfaces:**
- Produces `require_any_role(*roles: Role)` and routes under `/v1/curriculum-profiles` and `/v1/admin/curriculum`.
- Consumes Task 3 service methods and `CurrentPrincipal`.

- [ ] **Step 1: Write failing HTTP tests with teacher, student and admin identities**

```python
def test_teacher_filters_active_objectives_by_grade_domain_and_question_type(context: ApiContext) -> None:
    response = context.teacher.get(f"/v1/curriculum-profiles/{context.profile_id}/objectives?grade_level=G1&subject=mathematics&domain=number&question_type=M1")
    assert response.status_code == 200
    assert response.json()["items"][0]["revision"]["allowed_question_types"] == ["M1"]

def test_student_cannot_read_curriculum(context: ApiContext) -> None:
    assert context.student.get("/v1/curriculum-profiles").status_code == 404

def test_admin_activation_writes_audit_event(context: ApiContext) -> None:
    response = context.admin.post(f"/v1/admin/curriculum/objective-revisions/{context.draft_revision_id}/activate")
    assert response.status_code == 200
```

- [ ] **Step 2: Run API tests and verify failure**

Run: `python -m pytest apps/api/tests/test_curriculum.py -q`

Expected: 404 because no router is registered.

- [ ] **Step 3: Implement dependency and route contracts**

```python
def require_any_role(*roles: Role) -> Callable[[CurrentPrincipal], CurrentPrincipal]:
    def dependency(principal: Annotated[CurrentPrincipal, Depends(get_current_principal)]) -> CurrentPrincipal:
        if principal.role not in roles:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        return principal
    return dependency

router = APIRouter(prefix="/v1/curriculum-profiles", tags=["curriculum"])
admin_router = APIRouter(prefix="/v1/admin/curriculum", tags=["curriculum administration"])
```

Require teacher-or-admin for read routes and `Role.ADMIN` for all writes. Convert `CurriculumValidationError` to `HTTPException(422, detail={"code": error.code, "field": error.field, "message": error.message})`; do not leak draft/retired rows to readers.

- [ ] **Step 4: Run API and OpenAPI verification**

Run: `python -m pytest apps/api/tests/test_curriculum.py -q; python -m pytest apps/api/tests/test_health.py -q`

Expected: all pass and `/openapi.json` contains the curriculum tags and routes.

- [ ] **Step 5: Commit the HTTP slice**

```powershell
git add apps/api/src/edu_grader_api/dependencies.py apps/api/src/edu_grader_api/routers/curriculum.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_curriculum.py
git commit -m "feat: expose curriculum catalogue APIs"
```

### Task 5: Verify full integration and publish contract documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/ai-question-generation-plan.md`
- Test: `apps/api/tests/test_curriculum_models.py`
- Test: `apps/api/tests/test_curriculum.py`

**Interfaces:**
- Consumes the final API and four seed codes from Tasks 1–4.
- Produces documented read API entry points and migration command.

- [ ] **Step 1: Write failing contract assertions**

```python
def test_openapi_exposes_curriculum_read_routes() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    assert "/v1/curriculum-profiles" in schema["paths"]
    assert "/v1/curriculum-profiles/{profile_id}/objectives" in schema["paths"]
```

- [ ] **Step 2: Run the contract tests**

Run: `python -m pytest apps/api/tests/test_curriculum.py -q`

Expected: pass after Task 4; if it fails, correct the route registration before editing documentation.

- [ ] **Step 3: Add concise user-facing documentation**

Add the two read route families to `README.md`, state that K–13 is internal, that only short licensed-safe summaries are stored, and that later AI generation must retain profile and revision IDs. Keep the authoritative-source links in `docs/ai-question-generation-plan.md` unchanged.

- [ ] **Step 4: Run the complete validation suite**

Run: `python -m pytest apps/api/tests; python -m ruff format --check apps/api; python -m ruff check apps/api; python -m alembic -c apps/api/alembic.ini upgrade head; python -m alembic -c apps/api/alembic.ini downgrade 0012_guardian_consent_state_integrity; python -m alembic -c apps/api/alembic.ini upgrade head`

Expected: all API tests pass, Ruff exits 0, downgrade removes curriculum tables, and the final upgrade restores the four profile seed rows.

- [ ] **Step 5: Commit final documentation and verification coverage**

```powershell
git add README.md docs/ai-question-generation-plan.md apps/api/tests/test_curriculum.py apps/api/tests/test_curriculum_models.py
git commit -m "docs: document curriculum catalogue"
```
