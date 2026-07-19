# Privacy and Audit Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a pilot-safe minimum-data, de-identified grading, safe logging, and tamper-evident audit baseline for Issue #8.

**Architecture:** Identity remains in the Core API, while assignments and grading continue to use internal UUIDs. A central ledger service canonicalizes and HMAC-signs permitted audit events in the same transaction as the business write. Typed outbound payloads and processor URL checks guard both API-to-grader and grader-to-LanguageTool boundaries.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic Settings, SQLAlchemy 2, Alembic, PostgreSQL 16, Keycloak 26, pytest, Ruff.

## Global Constraints

- Never add a student phone field; retain `ck_students_require_school_id_and_no_email`.
- Only `iss`, `sub`, and `school_id` may be used for trusted OIDC roster binding. Grading payloads contain none of these fields.
- Audit metadata must never include an answer, name, email, school ID, OIDC subject, token, request header, or full request body.
- Production must fail at startup without a 32-byte HMAC key and processor-host allowlist.
- The audit ledger is tamper-evident; daily chain-head export to independent storage remains an operational prerequisite.
- Use PostgreSQL triggers plus Python stdlib `hashlib` and `hmac`; do not add an external service or database extension.

---

## File Structure

- Create `docs/data-inventory.md`: fields, purpose, classification, roles, processor, retention, and deletion trigger.
- Create `apps/api/src/edu_grader_api/audit.py`: audit metadata validation, canonical serialization, append, and verify operations.
- Create `apps/api/src/edu_grader_api/logging.py`: recursive structured-log sanitization.
- Create `apps/api/tests/test_audit.py` and `apps/api/tests/test_secure_logging.py`.
- Create `packages/processor-policy/pyproject.toml` and `packages/processor-policy/src/edu_grader_processor_policy/__init__.py`: shared processor URL and payload policy.
- Create `packages/processor-policy/tests/test_processor_policy.py`.
- Modify `apps/api/src/edu_grader_api/models.py`, `settings.py`, `auth.py`, `services/grader.py`, `services/assignments.py`, `services/questions.py`, `services/reviews.py`, `services/roster.py`, `routers/admin.py`, and `main.py`.
- Create `apps/api/alembic/versions/0007_privacy_audit_foundation.py`.
- Modify `Makefile`, `apps/api/Dockerfile`, `services/grader/Dockerfile`, `apps/api/pyproject.toml`, `services/grader/pyproject.toml`, `.env.example`, `compose.yaml`, `infra/keycloak/edu-grader-realm.json`, `SECURITY.md`, and `README.md`.

## Task 1: Inventory and OIDC minimization

**Files:**
- Create: `docs/data-inventory.md`
- Modify: `infra/keycloak/edu-grader-realm.json:21-29`
- Modify: `apps/api/tests/test_settings.py`

**Interfaces:** Produces a machine-reviewable realm scope assertion and the release-review data inventory.

- [ ] **Step 1: Write the failing scope test**

Add this test to `apps/api/tests/test_settings.py`:

    def test_web_client_requests_no_email_or_profile_scope() -> None:
        realm = json.loads(
            Path("infra/keycloak/edu-grader-realm.json").read_text(encoding="utf-8")
        )
        web = next(item for item in realm["clients"] if item["clientId"] == "edu-grader-web")
        assert "email" not in web["defaultClientScopes"]
        assert "profile" not in web["defaultClientScopes"]
        assert "school-id" in web["defaultClientScopes"]

- [ ] **Step 2: Confirm the test fails**

Run: `python -m pytest apps/api/tests/test_settings.py::test_web_client_requests_no_email_or_profile_scope -q`

Expected: FAIL because `email` and `profile` remain in the client scopes.

- [ ] **Step 3: Implement the scoped realm and inventory**

Replace the Web client's default scopes with exactly `web-origins`, `acr`, `roles`, `basic`, `edu-grader-api-audience`, and `school-id`.

Create `docs/data-inventory.md` with these mandatory rows:

| Record group | Tables | Class | Roles | Retention | Trigger |
| --- | --- | --- | --- | --- | --- |
| Identity/roster | `users`, `classes`, `class_teachers`, `enrollments` | restricted | admin; assigned teacher | active enrollment + 2 years | verified deletion after hold check |
| Student work/grade | `student_attempts`, `attempt_answers`, `grading_runs`, `grading_signals`, `grade_publications` | restricted | student self; assigned teacher; admin | 2 years after publication | expiry or approved request |
| Draft work | draft attempts and answers | restricted | student self; assigned teacher | 30 days after submission/abandonment | scheduled expiry |
| Appeals/corrections | `review_appeals`, `correction_attempts`, `review_decisions`, `review_tasks` | restricted | student self; assigned teacher; admin | 2 years after decision | expiry or approved request |
| Security audit | `audit_logs`, `audit_chain_heads` | confidential | admin; incident responder | 3 years | expiry after independent head export |

State that `school_id` is only for roster binding, phones are unsupported, and graders receive rule plus answer but no identity.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_auth.py -q`

Expected: PASS.

    git add docs/data-inventory.md infra/keycloak/edu-grader-realm.json apps/api/tests/test_settings.py
    git commit -m "docs: define privacy data inventory"

## Task 2: Processor policy and safe configuration

**Files:**
- Create: `packages/processor-policy/pyproject.toml`, `packages/processor-policy/src/edu_grader_processor_policy/__init__.py`, and `packages/processor-policy/tests/test_processor_policy.py`
- Modify: `Makefile`, `apps/api/src/edu_grader_api/settings.py`, `services/grader/src/edu_grader/main.py`, `apps/api/src/edu_grader_api/services/grader.py`, `apps/api/Dockerfile`, `services/grader/Dockerfile`, `apps/api/pyproject.toml`, `services/grader/pyproject.toml`, `.env.example`, and `compose.yaml`
- Test: `apps/api/tests/test_settings.py`, `apps/api/tests/test_english_grader_client.py`

**Interfaces:**
- Produces `assert_allowed_processor_url(url: str, allowed_hosts: frozenset[str]) -> None`.
- Produces `assert_deidentified_payload(payload: Mapping[str, object]) -> None`.
- Both raise `ProcessorPolicyError` on a prohibited destination or field.

- [ ] **Step 1: Write failing boundary tests**

Create `packages/processor-policy/tests/test_processor_policy.py`:

    def test_rejects_processor_host_not_in_allowlist() -> None:
        with pytest.raises(ProcessorPolicyError, match="not allowlisted"):
            assert_allowed_processor_url(
                "https://model.example/check", frozenset({"languagetool"})
            )

    def test_rejects_identity_field_in_nested_payload() -> None:
        with pytest.raises(ProcessorPolicyError, match="student_id"):
            assert_deidentified_payload(
                {"answer": {"text": "x", "student_id": "forbidden"}}
            )

Add API settings tests proving production rejects an empty `audit_hmac_key` and `processor_allowed_hosts`.

- [ ] **Step 2: Confirm they fail**

Run: `python -m pytest apps/api/tests/test_settings.py packages/processor-policy/tests/test_processor_policy.py -q`

Expected: FAIL because these interfaces and settings do not exist.

- [ ] **Step 3: Implement policy enforcement**

Define the forbidden key set as exactly:

    {
        "tenant_id", "student_id", "school_id", "display_name", "oidc_subject",
        "email", "phone", "metadata", "authorization", "token",
    }

Recursively reject those case-insensitive keys from dictionaries and lists. Parse URLs with `urllib.parse.urlparse`; allow `http` only for hostnames in the local allowlist and require `https` for all other hosts. Package this API as `edu-grader-processor-policy`; add its local path dependency to both API and Grader projects, make `install-python` install it editable before the API and Grader packages, and copy/install it in both Dockerfiles. Add API settings `audit_hmac_key`, `audit_hmac_key_version`, and comma-separated `processor_allowed_hosts`; validate production on construction. Validate `settings.grader_base_url` before every API-to-grader request. In the grader, validate `LANGUAGETOOL_BASE_URL` before constructing `LanguageToolClient` and validate `EnglishGradeRequest.model_dump()` before calling `grade_english`.

Add and pass through:

    AUDIT_HMAC_KEY=development-only-change-me-32-bytes-minimum
    AUDIT_HMAC_KEY_VERSION=dev-1
    PROCESSOR_ALLOWED_HOSTS=grader,languagetool,localhost

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_english_grader_client.py packages/processor-policy/tests/test_processor_policy.py -q`

Expected: PASS.

    git add packages/processor-policy Makefile apps/api/src/edu_grader_api/settings.py apps/api/src/edu_grader_api/services/grader.py services/grader/src/edu_grader/main.py apps/api/Dockerfile services/grader/Dockerfile apps/api/pyproject.toml services/grader/pyproject.toml .env.example compose.yaml apps/api/tests/test_settings.py
    git commit -m "feat: enforce deidentified processor policy"

## Task 3: Tamper-evident ledger schema and service

**Files:**
- Create: `apps/api/src/edu_grader_api/audit.py`
- Create: `apps/api/alembic/versions/0007_privacy_audit_foundation.py`
- Modify: `apps/api/src/edu_grader_api/models.py:183-198`
- Create: `apps/api/tests/test_audit.py`
- Modify: `apps/api/tests/test_models.py`, `apps/api/tests/test_class_access.py`

**Interfaces:**
- Produces `append_audit_event(session, *, tenant_id, actor_user_id, event_type, target_type, target_id, metadata) -> AuditLog`.
- Produces `verify_audit_chain(session, *, tenant_id) -> AuditChainVerification`.
- Produces `AuditChainHead(tenant_id, next_sequence, latest_entry_hash)` locked with `SELECT ... FOR UPDATE`.

- [ ] **Step 1: Write failing ledger tests**

    def test_append_links_and_signs_a_tenant_ledger(database_session, pilot, teacher) -> None:
        first = append_audit_event(
            database_session, tenant_id=pilot.id, actor_user_id=teacher.id,
            event_type="question.rule_changed", target_type="question_version",
            target_id=uuid4(), metadata={"version_number": 2},
        )
        second = append_audit_event(
            database_session, tenant_id=pilot.id, actor_user_id=teacher.id,
            event_type="grade.published", target_type="student_attempt",
            target_id=uuid4(), metadata={"assignment_id": str(uuid4())},
        )
        assert (first.sequence, second.sequence) == (1, 2)
        assert second.previous_hash == first.entry_hash
        assert verify_audit_chain(database_session, tenant_id=pilot.id).valid

    def test_verification_detects_modified_metadata(database_session, audit_entry) -> None:
        audit_entry.metadata_json = {"assignment_id": "substituted"}
        database_session.flush()
        result = verify_audit_chain(database_session, tenant_id=audit_entry.tenant_id)
        assert result.valid is False
        assert result.first_invalid_sequence == audit_entry.sequence

Also test independent tenant sequences, rejected metadata keys, and rejected answer/token values.

- [ ] **Step 2: Confirm they fail**

Run: `python -m pytest apps/api/tests/test_audit.py -q`

Expected: FAIL because no ledger service or ledger fields exist.

- [ ] **Step 3: Implement model, migration, and ledger**

Add non-null `sequence`, `previous_hash`, `entry_hash`, `signature`, and `key_version` to `AuditLog`. Add `AuditChainHead` keyed by tenant. Canonicalize metadata with UTF-8 JSON using `sort_keys=True` and compact separators. Hash exactly this mapping: tenant, actor UUID, event type, target type, target UUID, UTC timestamp, canonical metadata, sequence, previous hash, and key version. Use SHA-256 for `entry_hash`, then `hmac.new(key, entry_hash.encode(), hashlib.sha256).hexdigest()` for `signature`.

Backfill existing records in deterministic `(occurred_at, id)` tenant order using `key_version="legacy-unsigned"` before applying non-null constraints. The verifier accepts migrated unsigned records but verifies every newly written signature.

Install PostgreSQL-only mutation protection in the migration:

    CREATE FUNCTION prevent_audit_log_mutation() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'audit_logs are append-only';
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER audit_logs_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();

The SQLite unit suite validates ledger chaining; the Compose validation in Task 6 verifies the trigger.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_audit.py apps/api/tests/test_models.py apps/api/tests/test_class_access.py -q`

Expected: PASS.

    git add apps/api/src/edu_grader_api/audit.py apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0007_privacy_audit_foundation.py apps/api/tests/test_audit.py apps/api/tests/test_models.py apps/api/tests/test_class_access.py
    git commit -m "feat: add tamper-evident audit ledger"

## Task 4: Mandatory business events and atomicity

**Files:**
- Modify: `apps/api/src/edu_grader_api/auth.py:93-134`
- Modify: `apps/api/src/edu_grader_api/services/assignments.py:675-696`
- Modify: `apps/api/src/edu_grader_api/services/questions.py:100-120,167-190,281-334`
- Modify: `apps/api/src/edu_grader_api/services/reviews.py:194-365`
- Modify: `apps/api/src/edu_grader_api/services/roster.py:58-107`
- Modify: `apps/api/src/edu_grader_api/routers/admin.py:41-125`
- Test: `apps/api/tests/test_auth.py`, `test_questions.py`, `test_reviews.py`, `test_grade_publication.py`, `test_roster_import.py`

**Interfaces:**
- Business paths consume `append_audit_event` and do not construct `AuditLog` directly.
- Required event names are `auth.login_succeeded`, `auth.login_denied`, `data.export_requested`, `data.export_completed`, `question.rule_changed`, `grade.published`, and `review.score_adjusted`.

- [ ] **Step 1: Write failing controlled-event tests**

    entry = database_session.scalar(
        select(AuditLog).where(AuditLog.event_type == "review.score_adjusted")
    )
    assert entry.metadata_json == {
        "action": "adjust_score", "original_score": 0.0,
        "final_score": 1.0, "task_version": 0,
    }
    assert verify_audit_chain(database_session, tenant_id=entry.tenant_id).valid

Add a source assertion that `AuditLog(` appears only in `audit.py` outside tests. Test a failed trusted-tenant membership binding creates `auth.login_denied` with `correlation_id` and `reason`, never raw OIDC `sub` or `school_id`.

- [ ] **Step 2: Confirm they fail**

Run: `python -m pytest apps/api/tests/test_auth.py apps/api/tests/test_questions.py apps/api/tests/test_reviews.py apps/api/tests/test_grade_publication.py apps/api/tests/test_roster_import.py -q`

Expected: FAIL because legacy direct writes and event names remain.

- [ ] **Step 3: Replace writers and normalize events**

Use `append_audit_event` for every existing audit call. Map draft save to `question.rule_changed` with `{version_number, changed_fields}`, publication to `grade.published` with `{assignment_id}`, and adjustment to `review.score_adjusted` with `{action, original_score, final_score, task_version}`. Keep non-adjustment decisions as `review.decision_recorded`, submissions as `student_attempt.submitted`, and roster/class events by their existing names with IDs/counts only.

Add an admin-only `POST /v1/admin/audit-exports` endpoint. It emits `data.export_requested`, validates the chain, assembles only safe display fields, emits `data.export_completed`, and returns the records. Do not return hash, signature, actor UUID, or unapproved metadata fields.

- [ ] **Step 4: Add atomicity tests and verify**

Monkeypatch `append_audit_event` to raise `AuditWriteError`; verify question mutation, teacher score adjustment, and grade publication return 503 and leave no database mutation.

Run: `python -m pytest apps/api/tests/test_auth.py apps/api/tests/test_questions.py apps/api/tests/test_reviews.py apps/api/tests/test_grade_publication.py apps/api/tests/test_roster_import.py apps/api/tests/test_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

    git add apps/api/src/edu_grader_api/auth.py apps/api/src/edu_grader_api/services apps/api/src/edu_grader_api/routers/admin.py apps/api/tests
    git commit -m "feat: record protected audit events"

## Task 5: Safe application logging and release evidence

**Files:**
- Create: `apps/api/src/edu_grader_api/logging.py`
- Create: `apps/api/tests/test_secure_logging.py`
- Modify: `apps/api/src/edu_grader_api/main.py`, `SECURITY.md`, `README.md`

**Interfaces:**
- Produces `sanitize_log_fields(fields: Mapping[str, object]) -> dict[str, object]`.
- Produces `get_secure_logger(name: str) -> logging.LoggerAdapter`.

- [ ] **Step 1: Write failing redaction tests**

    def test_nested_answer_tokens_and_identity_are_never_emitted(caplog) -> None:
        logger = get_secure_logger("test")
        logger.info("submission.failed", extra={"fields": {
            "answer_json": {"answer": "student answer", "school_id": "S-1"},
            "authorization": "Bearer secret", "email": "student@example.test",
        }})
        assert "student answer" not in caplog.text
        assert "Bearer secret" not in caplog.text
        assert "student@example.test" not in caplog.text
        assert "[REDACTED]" in caplog.text

Add a case for `bad\nforged=entry` proving CR/LF and control characters are escaped while a correlation UUID remains visible.

- [ ] **Step 2: Confirm it fails**

Run: `python -m pytest apps/api/tests/test_secure_logging.py -q`

Expected: FAIL because the secure logger does not exist.

- [ ] **Step 3: Implement and document**

Recursively redact these case-insensitive keys: `answer`, `answer_json`, `authorization`, `token`, `password`, `oidc_subject`, `school_id`, `display_name`, `email`, `database_url`, and `connection_string`. Escape CR, LF, and all remaining ASCII control characters in permitted strings. Configure JSON structured logging during FastAPI startup. Do not log request bodies, headers, ORM instances, or exception representations.

Add the production release checklist to `SECURITY.md`: HMAC key rotation, allowlist review, daily independent chain-head export, Keycloak event retention/export, and no student-work inspection through ordinary logs. Link `docs/data-inventory.md` from `README.md`.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_secure_logging.py apps/api/tests/test_health.py -q`

Expected: PASS.

    git add apps/api/src/edu_grader_api/logging.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_secure_logging.py SECURITY.md README.md
    git commit -m "feat: redact sensitive application logs"

## Task 6: PostgreSQL migration and full verification

**Files:**
- Modify: `docs/data-inventory.md` only if implementation reveals an undocumented record, processor, or retention rule.

- [ ] **Step 1: Run static and full test suites**

    make api-lint
    make api-test
    python -m pytest packages/processor-policy/tests services/grader/tests -q

Expected: all commands exit 0.

- [ ] **Step 2: Verify migration and append guard in Compose**

    docker compose up -d postgres keycloak-postgres keycloak languagetool grader api
    docker compose exec api python -m alembic -c alembic.ini upgrade head

Insert a disposable `audit_logs` record through the ledger, then run:

    docker compose exec postgres psql -U edu_grader -d edu_grader -c "UPDATE audit_logs SET event_type = 'tampered' WHERE sequence = 1;"

Expected: PostgreSQL rejects the update with `audit_logs are append-only`; use isolated local test teardown to discard the disposable row and never bypass the guard.

- [ ] **Step 3: Verify production startup guard**

    docker compose run --rm -e APP_ENV=production -e AUDIT_HMAC_KEY= -e PROCESSOR_ALLOWED_HOSTS= api python -c "import edu_grader_api.settings"

Expected: nonzero exit naming the missing production controls.

- [ ] **Step 4: Confirm complete coverage**

Verify `rg -n "AuditLog\(" apps/api/src` lists only `audit.py`; verify `rg -n "httpx.post|LanguageToolClient" apps/api/src services/grader/src` identifies only policy-guarded call sites. Reconcile every table, processor, and protected event with `docs/data-inventory.md`.

- [ ] **Step 5: Commit only material inventory corrections**

    git add docs/data-inventory.md
    git commit -m "docs: record privacy baseline verification"

If no inventory correction was required, do not create an empty commit. Post the passing commands, migration evidence, and remaining Issue #8 slices—guardian consent, data-subject requests, backup/restore, incident drill, and PIA—to the issue before declaring this first slice complete.
