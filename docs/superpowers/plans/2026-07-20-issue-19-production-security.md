# Issue 19 Production Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make production configuration and guardian-consent processing fail closed without exposing secrets or student identifiers.

**Architecture:** `Settings` remains the Core API startup boundary and gains an explicit reviewed production processor-host set. The consent dependency logs only a classification when a record is absent. Existing Kubernetes Secret generation and production-Realm tests become the deployment boundary for Keycloak credentials and demo identities.

**Tech Stack:** Python 3.13, FastAPI, Pydantic Settings, SQLAlchemy, pytest, Pester, Kubernetes.

## Global Constraints

- Production permits only `grader` and `languagetool` in `PROCESSOR_ALLOWED_HOSTS`; `localhost` stays valid only outside production.
- `/ready` exposes only component status, never a secret, URL, student identifier, answer, or token.
- A missing consent record returns `403 {"detail": "guardian consent required"}` and logs no student or school identifier.
- Keycloak bootstrap secrets are created by `scripts/k8s/create-prod-secrets.ps1`, not loaded by the Core API.

---

### Task 1: Fail closed on unreviewed production processor hosts

**Files:**
- Modify: `apps/api/tests/test_settings.py`
- Modify: `apps/api/src/edu_grader_api/settings.py`

**Interfaces:**
- Produces `PRODUCTION_PROCESSOR_HOSTS: frozenset[str]` containing `{"grader", "languagetool"}`.
- `Settings.require_production_security_controls()` rejects any configured host outside that set.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("processor_allowed_hosts", ["grader,external.example", "localhost"])
def test_production_settings_reject_unreviewed_processor_hosts(
    processor_allowed_hosts: str,
) -> None:
    with pytest.raises(ValueError, match="PROCESSOR_ALLOWED_HOSTS"):
        Settings(
            app_env="production",
            audit_hmac_key="x" * 32,
            database_url="postgresql://edu_grader:secure-password@db.example/edu_grader",
            oidc_issuer="https://identity.example/realms/edu-grader",
            processor_allowed_hosts=processor_allowed_hosts,
        )


def test_development_settings_keep_local_processor_support() -> None:
    assert Settings(processor_allowed_hosts="grader,localhost").allowed_processor_hosts == {
        "grader",
        "localhost",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/api/tests/test_settings.py -q`

Expected: the external-host and localhost production cases fail because the current validator only rejects an empty or wildcard allowlist.

- [ ] **Step 3: Write minimal implementation**

```python
PRODUCTION_PROCESSOR_HOSTS = frozenset({"grader", "languagetool"})

# Inside the existing production block, after the wildcard check:
if not self.allowed_processor_hosts.issubset(PRODUCTION_PROCESSOR_HOSTS):
    raise ValueError(
        "PROCESSOR_ALLOWED_HOSTS must contain only reviewed internal processors in production"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/api/tests/test_settings.py -q`

Expected: all settings tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/settings.py apps/api/tests/test_settings.py
git commit -m "fix: restrict production processor hosts"
```

### Task 2: Audit missing consent without identity leakage

**Files:**
- Modify: `apps/api/tests/test_guardian_consents.py`
- Modify: `apps/api/src/edu_grader_api/dependencies.py`

**Interfaces:**
- `require_student_consent()` logs `guardian_consent.missing_record` with a `reason` field only when `session.get()` returns `None`.
- Its HTTP result remains unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_missing_guardian_consent_blocks_without_logging_student_identity(
    client: TestClient, session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    _, student = student_and_admin(session)
    session.delete(session.get(StudentGuardianConsent, student.id))
    session.commit()

    with caplog.at_level(logging.WARNING):
        response = client.get("/v1/student/assignments", headers=authorize(client, student))

    assert response.status_code == 403
    assert "guardian_consent.missing_record" in caplog.text
    assert "missing_record" in caplog.text
    assert str(student.id) not in caplog.text
    assert student.school_id not in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/api/tests/test_guardian_consents.py -q`

Expected: the new test fails because no warning is emitted.

- [ ] **Step 3: Write minimal implementation**

```python
from .logging import get_secure_logger

logger = get_secure_logger(__name__)

# Immediately after reading consent in require_student_consent:
if consent is None:
    logger.warning(
        "guardian_consent.missing_record", extra={"fields": {"reason": "missing_record"}}
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/api/tests/test_guardian_consents.py apps/api/tests/test_secure_logging.py -q`

Expected: the request remains blocked and the log contains no identity value.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/dependencies.py apps/api/tests/test_guardian_consents.py
git commit -m "fix: audit missing guardian consent safely"
```

### Task 3: Capture production-secret and realm evidence

**Files:**
- Modify: `scripts/k8s/create-prod-secrets.tests.ps1`
- Modify: `apps/api/tests/test_production_keycloak_realm.py`
- Modify: `SECURITY.md`

**Interfaces:**
- The Secret-generator test proves its source contains no development default and does not write secret values.
- The production-Realm test proves no development users or `pilot-` identity remains.

- [ ] **Step 1: Write the failing tests**

```powershell
It 'contains no development defaults in the production Secret generator' {
    $source = Get-Content -Raw $scriptPath

    $source | Should Not Match 'change-me|development-only-change-me|pilot-(admin|teacher|student)'
}
```

```python
def test_production_realm_has_no_development_identity_artifacts() -> None:
    realm_text = REALM_PATH.read_text(encoding="utf-8")

    assert "pilot-admin" not in realm_text
    assert "pilot-teacher" not in realm_text
    assert "pilot-student" not in realm_text
```

- [ ] **Step 2: Run test to verify it fails or record existing coverage**

Run: `Invoke-Pester scripts/k8s/create-prod-secrets.tests.ps1 -Output Detailed; python -m pytest apps/api/tests/test_production_keycloak_realm.py -q`

Expected: add only assertions that expose a real artifact. If these tests are already green, record that the generator and Realm already satisfy this acceptance item and do not change production code.

- [ ] **Step 3: Add operational documentation**

Append this exact release check to `SECURITY.md`:

```markdown
- 生产部署只运行 `scripts/k8s/create-prod-secrets.ps1` 生成的 Secret；不得使用 `.env.example`、Compose 开发 Keycloak 或 `pilot-*` 演示身份。轮换后确认 API `/ready` 与 Keycloak Realm 探针均成功，再删除旧 Secret。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/api/tests/test_production_keycloak_realm.py -q`

Expected: production Realm test passes. If Pester is available, its test also passes; otherwise report the unavailable runner and retain the source-level Python coverage.

- [ ] **Step 5: Commit**

```powershell
git add scripts/k8s/create-prod-secrets.tests.ps1 apps/api/tests/test_production_keycloak_realm.py SECURITY.md
git commit -m "docs: document production secret controls"
```

### Task 4: Full issue verification and GitHub closure

**Files:**
- Verify only.

- [ ] **Step 1: Run focused issue verification**

Run: `python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_guardian_consents.py apps/api/tests/test_guardian_consent_integrity.py apps/api/tests/test_guardian_consent_integrity_cli.py apps/api/tests/test_health.py apps/api/tests/test_production_keycloak_realm.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run repository quality gates**

Run: `python -m ruff format --check packages/processor-policy apps/api services/grader; python -m ruff check packages/processor-policy apps/api services/grader; python -m pytest packages/processor-policy/tests apps/api/tests services/grader/tests -q`

Expected: format, lint, and all Python tests pass.

- [ ] **Step 3: Verify deployment configuration**

Run: `docker compose config --quiet`

Expected: Compose renders when required local development variables are supplied. Run `Invoke-Pester scripts/k8s/create-prod-secrets.tests.ps1 -Output Detailed` when Pester is installed.

- [ ] **Step 4: Push and close #19**

Run: `git status --short; git log --oneline main..HEAD`

Expected: only the design, implementation, tests, and documentation listed above are present. Push the branch, then close GitHub issue #19 with a comment linking the validation evidence.

