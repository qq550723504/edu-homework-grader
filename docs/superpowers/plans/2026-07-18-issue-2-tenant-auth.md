# Issue 2 Tenant Identity Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Deliver tenant-isolated OIDC identities, classes, roster import, role authorization, and append-only audit events for the pilot.

**Architecture:** Keycloak owns credentials and issues OpenID Connect access tokens. FastAPI verifies the token through an injectable verifier, resolves a database-backed CurrentPrincipal, and applies tenant-scoped service rules. SQLAlchemy 2 models and Alembic migrations own all business persistence; Keycloak identity data never enters the application database.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, psycopg 3, PyJWT crypto, PostgreSQL 16, Keycloak, Docker Compose, pytest, httpx.

## Global Constraints

- Validate JWT signature, issuer, audience, expiry, and subject before using claims.
- Never log an access token, full JWT claims, student answer, or password.
- Never trust a client-provided tenant ID or raw token role for authorization; the trusted OIDC_TENANT_SLUG configuration selects the pilot tenant.
- Invalid or absent authentication returns 401; authenticated cross-tenant or membership-ineligible entity access returns 404.
- Students have no required email and no local password; their OIDC subject is bound only after a verified first login.
- Each data-changing account, class, enrollment, assignment, or import action appends an audit record.
- All production behavior begins with a failing automated test and ends with a passing focused test plus the full API suite.

---

## File structure

| File | Responsibility |
| --- | --- |
| apps/api/src/edu_grader_api/db.py | SQLAlchemy engine, session factory, request dependency, and declarative base. |
| apps/api/src/edu_grader_api/models.py | Tenant, user, class, relationship, and append-only audit ORM models. |
| apps/api/src/edu_grader_api/auth.py | OIDC Discovery/JWKS verification interfaces and principal resolution. |
| apps/api/src/edu_grader_api/dependencies.py | Reusable role and class-access FastAPI dependencies. |
| apps/api/src/edu_grader_api/services/roster.py | Transactional CSV parsing, idempotent import, and audit writes. |
| apps/api/src/edu_grader_api/routers/admin.py | Tenant administrator routes. |
| apps/api/src/edu_grader_api/routers/classes.py | Tenant-scoped class read route. |
| apps/api/alembic/ | Alembic environment and revision history. |
| apps/api/tests/conftest.py | SQLite test database, app overrides, and identity fixtures. |
| infra/keycloak/edu-grader-realm.json | Versioned development realm. |
| compose.yaml and .env.example | Keycloak, migrations, and OIDC configuration. |

## Interfaces

~~~
class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    school_id: str | None

@dataclass(frozen=True)
class CurrentPrincipal:
    user_id: UUID
    tenant_id: UUID
    role: Role

class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity: ...

def get_current_principal(...) -> CurrentPrincipal: ...
def import_roster(session: Session, actor: CurrentPrincipal, rows: list[RosterRow]) -> RosterImportResult: ...
~~~

### Task 1: Add persistent tenant and membership schema

**Files:**
- Create: apps/api/src/edu_grader_api/db.py
- Create: apps/api/src/edu_grader_api/models.py
- Create: apps/api/alembic.ini, apps/api/alembic/env.py, apps/api/alembic/versions/0001_tenant_identity.py
- Modify: apps/api/pyproject.toml
- Test: apps/api/tests/test_models.py

**Consumes:** Existing FastAPI settings and PostgreSQL URL.

**Produces:** Base, get_session(), Role, and mapped Tenant, User, Classroom, ClassTeacher, Enrollment, and AuditLog types.

- [ ] **Step 1: Write the failing persistence test**

~~~
def test_student_school_id_is_unique_within_a_tenant() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(slug="pilot-a", name="Pilot A")
        session.add_all([
            tenant,
            User(tenant=tenant, role=Role.STUDENT, school_id="S-001", display_name="One"),
            User(tenant=tenant, role=Role.STUDENT, school_id="S-001", display_name="Two"),
        ])
        with pytest.raises(IntegrityError):
            session.commit()
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest apps/api/tests/test_models.py::test_student_school_id_is_unique_within_a_tenant -q

Expected: FAIL with ModuleNotFoundError for edu_grader_api.models.

- [ ] **Step 3: Write minimal persistence implementation**

Add these production dependencies to apps/api/pyproject.toml:

~~~
"sqlalchemy>=2.0,<2.1",
"alembic>=1.16,<2",
"psycopg[binary]>=3.2,<4",
"pyjwt[crypto]>=2.10,<3",
"python-multipart>=0.0.20,<1",
~~~

Map tenants, users, classes, class_teachers, enrollments, and audit_logs with UUID primary keys and timezone-aware timestamps. Define these constraints exactly:

~~~
UniqueConstraint("tenant_id", "school_id", name="uq_users_tenant_school_id")
UniqueConstraint("tenant_id", "code", name="uq_classes_tenant_code")
UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity")
PrimaryKeyConstraint("class_id", "teacher_id")
PrimaryKeyConstraint("class_id", "student_id")
~~~

Use Enum(Role, native_enum=False). A student has a non-null school ID and null work email. OIDC issuer and subject stay nullable until first verified login. Generate Alembic revision 0001_tenant_identity with matching upgrade and downgrade operations. Set target_metadata to Base.metadata and obtain the URL from DATABASE_URL.

- [ ] **Step 4: Run tests and migration checks**

Run:

~~~
python -m pytest apps/api/tests/test_models.py -q
python -m alembic -c apps/api/alembic.ini upgrade head
python -m alembic -c apps/api/alembic.ini downgrade base
~~~

Expected: tests PASS; upgrade and downgrade complete without a schema exception.

- [ ] **Step 5: Format, lint, and commit**

Run: python -m ruff format apps/api && python -m ruff check apps/api

~~~
git add apps/api
git commit -m "feat(api): add tenant identity schema"
~~~

### Task 2: Configure Keycloak and explicit bootstrap administration

**Files:**
- Create: infra/keycloak/edu-grader-realm.json
- Create: apps/api/src/edu_grader_api/bootstrap.py
- Modify: apps/api/src/edu_grader_api/settings.py, apps/api/src/edu_grader_api/main.py, compose.yaml, .env.example, README.md
- Test: apps/api/tests/test_settings.py, apps/api/tests/test_bootstrap.py

**Consumes:** Task 1 Tenant, User, and session factory.

**Produces:** Valid development OIDC configuration and one idempotently seeded administrator.

- [ ] **Step 1: Write failing settings and bootstrap tests**

~~~
def test_settings_exposes_required_oidc_configuration() -> None:
    settings = Settings(
        oidc_issuer="http://keycloak:8080/realms/edu-grader",
        oidc_audience="edu-grader-api",
        bootstrap_admin_sub="admin-subject",
        bootstrap_admin_tenant_slug="pilot",
    )
    assert settings.oidc_school_id_claim == "school_id"

def test_bootstrap_admin_is_idempotent(session: Session) -> None:
    first = bootstrap_admin(session, subject="admin-subject", tenant_slug="pilot")
    second = bootstrap_admin(session, subject="admin-subject", tenant_slug="pilot")
    assert first.id == second.id
    assert second.role is Role.ADMIN
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_bootstrap.py -q

Expected: FAIL because OIDC settings and bootstrap_admin do not exist.

- [ ] **Step 3: Implement only the tested configuration**

Add settings named oidc_issuer, oidc_audience, oidc_school_id_claim with default school_id, bootstrap_admin_sub, and bootstrap_admin_tenant_slug. bootstrap_admin creates one configured tenant and one Role.ADMIN user bound to issuer and subject; reruns return the same user and never alter a non-admin row.

Add a pinned Keycloak Compose service with start-dev --import-realm and a read-only realm mount:

~~~
volumes:
  - ./infra/keycloak:/opt/keycloak/data/import:ro
command: ["start-dev", "--import-realm"]
~~~

The realm defines admin, teacher, student roles; the edu-grader-api audience; and a school_id protocol mapper. Document only development credentials from .env, never a production password.

- [ ] **Step 4: Verify configuration**

Run:

~~~
python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_bootstrap.py -q
docker compose config
~~~

Expected: tests PASS and Compose prints a valid expanded configuration.

- [ ] **Step 5: Format, lint, and commit**

Run: python -m ruff format apps/api && python -m ruff check apps/api

~~~
git add apps/api infra/keycloak compose.yaml .env.example README.md
git commit -m "feat(auth): add development Keycloak realm"
~~~

### Task 3: Verify OIDC tokens and resolve principals safely

**Files:**
- Create: apps/api/src/edu_grader_api/auth.py, apps/api/src/edu_grader_api/dependencies.py
- Modify: apps/api/src/edu_grader_api/main.py, apps/api/tests/conftest.py
- Test: apps/api/tests/test_auth.py

**Consumes:** Task 1 models and Task 2 OIDC configuration.

**Produces:** TokenVerifier, VerifiedIdentity, CurrentPrincipal, and get_current_principal.

- [ ] **Step 1: Write failing authentication tests**

~~~
@pytest.mark.parametrize("identity", [
    VerifiedIdentity(issuer="wrong-issuer", subject="s-1", school_id="S-001"),
    VerifiedIdentity(issuer=ISSUER, subject="", school_id="S-001"),
])
def test_invalid_verified_identity_returns_401(client, identity) -> None:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(identity)
    response = client.get("/v1/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == 401

def test_first_student_login_binds_rostered_identity(client, session, student) -> None:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(ISSUER, "subject-1", student.school_id)
    )
    response = client.get("/v1/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert session.get(User, student.id).oidc_subject == "subject-1"
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: python -m pytest apps/api/tests/test_auth.py -q

Expected: FAIL because /v1/me and authentication dependencies do not exist.

- [ ] **Step 3: Implement verifier and principal lookup**

Implement PyJWKTokenVerifier: load issuer discovery metadata, obtain jwks_uri, use jwt.PyJWKClient, accept only RS256, and call jwt.decode with issuer, audience, and algorithms=[RS256]. Convert only verified iss, sub, and the configured school-id claim into VerifiedIdentity.

Implement get_current_principal with HTTPBearer(auto_error=False). Missing credentials, token verification errors, missing sub, and issuer mismatch raise 401. Resolve a bound issuer and subject first. For an unbound student, use trusted OIDC_TENANT_SLUG and match a unique student by school_id inside that tenant, bind issuer and subject in the same transaction, and return the database role. Unknown verified identities raise 403.

Add GET /v1/me returning id, tenant_id, role, school_id, and display_name.

- [ ] **Step 4: Verify focused and complete API tests**

Run:

~~~
python -m pytest apps/api/tests/test_auth.py -q
python -m pytest apps/api/tests -q
~~~

Expected: PASS.

- [ ] **Step 5: Format, lint, and commit**

Run: python -m ruff format apps/api && python -m ruff check apps/api

~~~
git add apps/api
git commit -m "feat(api): verify oidc identities"
~~~

### Task 4: Add transactional roster import and administrator class management

**Files:**
- Create: apps/api/src/edu_grader_api/services/__init__.py, apps/api/src/edu_grader_api/services/roster.py
- Create: apps/api/src/edu_grader_api/routers/__init__.py, apps/api/src/edu_grader_api/routers/admin.py
- Modify: apps/api/src/edu_grader_api/main.py
- Test: apps/api/tests/test_roster_import.py, apps/api/tests/test_admin.py

**Consumes:** Task 3 current principal and Task 1 persistence.

**Produces:** Admin-only CSV import, class creation, teacher assignment, and audit events.

- [ ] **Step 1: Write failing import tests**

~~~
def test_invalid_csv_rolls_back_every_row(admin_client, session) -> None:
    csv_body = (
        "class_code,class_name,student_school_id,student_display_name\n"
        "7A,Year 7 A,S-001,Ada\n"
        "7A,Year 7 A,S-001,Duplicate\n"
    )
    response = admin_client.post("/v1/admin/students/import", files={"file": ("roster.csv", csv_body)})
    assert response.status_code == 422
    assert session.scalar(select(func.count(User.id))) == 1

def test_reimport_updates_name_without_duplicate_enrollment(admin_client, session) -> None:
    first = "class_code,class_name,student_school_id,student_display_name\n7A,Year 7 A,S-001,Ada\n"
    second = "class_code,class_name,student_school_id,student_display_name\n7A,Year 7 A,S-001,Ada Lovelace\n"
    assert admin_client.post("/v1/admin/students/import", files={"file": ("r.csv", first)}).status_code == 200
    assert admin_client.post("/v1/admin/students/import", files={"file": ("r.csv", second)}).status_code == 200
    assert session.scalar(select(func.count(Enrollment.class_id))) == 1
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: python -m pytest apps/api/tests/test_roster_import.py apps/api/tests/test_admin.py -q

Expected: FAIL because the admin router and roster service do not exist.

- [ ] **Step 3: Implement service and routes**

Parse UTF-8 CSV with exactly class_code, class_name, student_school_id, and student_display_name headings. Reject blank values, duplicate student IDs in one input, and duplicate class codes with conflicting names; error details include the source row. Validate the whole file before session.begin(). In one transaction get-or-create tenant-local classes and students, update only a student display name, get-or-create enrollments, and append roster.imported audit rows. On validation or persistence failure, return 422 and roll back all rows.

Use require_role(Role.ADMIN) for every admin route. POST /v1/admin/classes takes code and name. The teacher assignment route verifies that user and class share the tenant and that the user role is teacher; otherwise return 404. Each successful change appends an audit event.

- [ ] **Step 4: Verify tests**

Run:

~~~
python -m pytest apps/api/tests/test_roster_import.py apps/api/tests/test_admin.py -q
python -m pytest apps/api/tests -q
~~~

Expected: PASS with no duplicate user, class, enrollment, or audit row after a valid reimport.

- [ ] **Step 5: Format, lint, and commit**

Run: python -m ruff format apps/api && python -m ruff check apps/api

~~~
git add apps/api
git commit -m "feat(api): import tenant class rosters"
~~~

### Task 5: Enforce class access and expose append-only audit history

**Files:**
- Create: apps/api/src/edu_grader_api/routers/classes.py
- Modify: apps/api/src/edu_grader_api/dependencies.py, apps/api/src/edu_grader_api/routers/admin.py, apps/api/src/edu_grader_api/main.py
- Test: apps/api/tests/test_class_access.py, apps/api/tests/test_audit_logs.py

**Consumes:** Task 4 membership data and audit records.

**Produces:** GET /v1/classes/{class_id} and paginated admin audit history with tenant isolation.

- [ ] **Step 1: Write failing authorization tests**

~~~
@pytest.mark.parametrize("client_name, expected", [
    ("assigned_teacher_client", 200),
    ("enrolled_student_client", 200),
    ("other_tenant_admin_client", 404),
    ("unassigned_teacher_client", 404),
    ("unenrolled_student_client", 404),
])
def test_class_visibility_is_limited_to_membership(request, class_id, client_name, expected) -> None:
    response = request.getfixturevalue(client_name).get(f"/v1/classes/{class_id}")
    assert response.status_code == expected
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: python -m pytest apps/api/tests/test_class_access.py apps/api/tests/test_audit_logs.py -q

Expected: FAIL because routes and membership dependencies do not exist.

- [ ] **Step 3: Implement tenant-scoped routes**

GET /v1/classes/{class_id} always filters Classroom.tenant_id == principal.tenant_id. Permit administrators, assigned teachers, and enrolled students; return 404 for every other case. Return only id, code, and name.

GET /v1/admin/audit-logs accepts limit=50, offset=0, and optional event_type. Constrain limit to 1 through 100, filter strictly by tenant, order by occurred_at DESC then id DESC, and return items, limit, and offset. Do not implement audit mutation or deletion routes.

- [ ] **Step 4: Verify tests**

Run:

~~~
python -m pytest apps/api/tests/test_class_access.py apps/api/tests/test_audit_logs.py -q
python -m pytest apps/api/tests -q
~~~

Expected: PASS; all cross-tenant and non-member probes return 404.

- [ ] **Step 5: Format, lint, and commit**

Run: python -m ruff format apps/api && python -m ruff check apps/api

~~~
git add apps/api
git commit -m "feat(api): enforce class membership access"
~~~

### Task 6: Run production-equivalent verification and finish documentation

**Files:**
- Modify: Makefile, README.md, CONTRIBUTING.md
- Test: apps/api/tests/test_migrations.py

**Consumes:** Tasks 1 through 5.

**Produces:** Repeatable test, migration, and local startup procedure.

- [ ] **Step 1: Write failing migration smoke test**

~~~
def test_alembic_upgrades_a_blank_postgres_database() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"],
        check=False, text=True, capture_output=True,
        env={**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]},
    )
    assert result.returncode == 0, result.stderr
~~~

- [ ] **Step 2: Run it to verify the current command and environment are correct**

Run: $env:TEST_DATABASE_URL='postgresql+psycopg://edu_grader:change-me@localhost:5432/edu_grader_test'; python -m pytest apps/api/tests/test_migrations.py -q

Expected: FAIL before the test database and migration target configuration are finalized, or PASS only after a blank PostgreSQL database has upgraded to head.

- [ ] **Step 3: Add verification commands and documentation**

Add api-test, api-migrate, and api-lint Make targets. Document exact local steps: copy .env.example, start Compose, run docker compose exec api python -m alembic -c alembic.ini upgrade head, obtain a development Keycloak token, and run the API suite. State that Keycloak development credentials and the realm file are local-only fixtures, while real student data and production secrets must never be committed.

- [ ] **Step 4: Run the complete gate**

Run:

~~~
python -m pytest apps/api/tests services/grader/tests -q
python -m ruff check apps/api services/grader
python -m ruff format --check apps/api services/grader
docker compose config
git diff --check
~~~

Expected: all tests and lint commands PASS, Compose validates, and diff check has no whitespace errors.

- [ ] **Step 5: Commit the verified finish**

~~~
git add Makefile README.md CONTRIBUTING.md apps/api
git commit -m "docs: document tenant identity operations"
~~~
