# Student Activation Codes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow teachers to issue seven-day, one-time student activation codes without retaining plaintext credentials.

**Architecture:** The API owns authorization and activation state. A narrowly scoped Keycloak Admin adapter creates student identities and temporary passwords. The Nuxt workbench performs an immediate CSV download through its existing BFF. A realm-sync Job configures the existing realm and an expiry CronJob disables unused expired credentials.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, httpx, Keycloak Admin REST API, Nuxt 3/Nitro/Vitest, Kubernetes Kustomize.

## Global Constraints

- Activation codes are high-entropy temporary Keycloak passwords, valid for exactly seven days.
- Store only an HMAC fingerprint; never store or log code, password, secret, school ID, or display name.
- Keycloak username and user attribute school_id equal the student school ID. The assigned realm role is student.
- Teachers can act only within their own classes. A student already bound to an OIDC subject is never reset here.
- The issuing response has no-store caching and attachment disposition. A lost code is reissued, never recovered.
- API and expiry workloads receive only provisioner credentials; administrator credentials mount only in the realm-sync Job.
- Existing CSV roster import remains roster-only.

---

## File Structure

- API model/migration: apps/api/src/edu_grader_api/models.py and apps/api/alembic/versions/0025_student_activations.py.
- API services: apps/api/src/edu_grader_api/services/keycloak_admin.py and apps/api/src/edu_grader_api/services/student_activations.py.
- API route/auth/operations: apps/api/src/edu_grader_api/routers/teacher.py, auth.py, cli/reconcile_keycloak_realm.py, and cli/expire_student_activations.py.
- API tests: test_student_activations.py, test_keycloak_admin.py, test_teacher_roster.py, test_auth.py, and test_settings.py.
- Web: apps/web/app/lib/teacher-api.ts, pages/teacher/index.vue, server/api/core/[...path].ts, and corresponding Vitest tests.
- Platform: development and production realm JSON, production application manifest, realm-sync Job, expiry CronJob, Kustomization, compose YAML, environment example, and README.

### Task 1: Add the activation lifecycle persistence

**Files:**
- Modify: apps/api/src/edu_grader_api/models.py
- Create: apps/api/alembic/versions/0025_student_activations.py
- Create: apps/api/tests/test_student_activations.py
- Modify: apps/api/tests/test_curriculum_models.py

**Interfaces:**
- StudentActivationStatus has provisioning, issued, consumed, expired, revoked, and failed.
- StudentActivation contains student ID, class ID, Keycloak user ID, code HMAC, status, issue/disclosure/expiry/consume/revoke timestamps, failure reason, issuer ID, and request ID.
- Migration revision 0025_student_activations follows 0024_generation_governance_entries.

- [ ] **Step 1: Write failing model and migration tests**

Test a valid issued activation, a missing fingerprint rejection for an issued row, index presence, and migration upgrade/downgrade. Also assert the latest Alembic head is 0025_student_activations.

- [ ] **Step 2: Run red tests**

Run: python -m pytest apps/api/tests/test_student_activations.py apps/api/tests/test_curriculum_models.py -q

Expected: FAIL because the lifecycle model and revision do not exist.

- [ ] **Step 3: Implement the model and migration**

Add the enum and model. Use UUID primary/request IDs, user/class foreign keys, timezone-aware timestamps, status constraints, user/class relationships, and indexes on student-plus-status and status-plus-expiry. Make the migration fully reversible.

- [ ] **Step 4: Run green tests**

Run: python -m pytest apps/api/tests/test_student_activations.py apps/api/tests/test_curriculum_models.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

Run: git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0025_student_activations.py apps/api/tests/test_student_activations.py apps/api/tests/test_curriculum_models.py

Run: git commit -m "feat: add student activation lifecycle"

### Task 2: Implement constrained Keycloak provisioning

**Files:**
- Modify: apps/api/src/edu_grader_api/settings.py
- Create: apps/api/src/edu_grader_api/services/keycloak_admin.py
- Create: apps/api/src/edu_grader_api/services/student_activations.py
- Create: apps/api/tests/test_keycloak_admin.py
- Modify: apps/api/tests/test_student_activations.py and apps/api/tests/test_settings.py

**Interfaces:**
- KeycloakAdmin ensures a student identity from school ID, display name, and code, returning Keycloak subject ID; it can replace a temporary password with an unknown value.
- issue_activations returns rows containing plaintext only in memory for response rendering.
- expire_activations returns the number of terminally expired rows.
- Settings expose Keycloak base URL, provisioner client ID/secret, activation HMAC key, and expiry days.

- [ ] **Step 1: Write failing adapter and service tests**

Mock Keycloak HTTP calls. Assert client-credential token exchange, lookup-or-create by school ID, school ID attribute write, student role assignment, and temporary password write. Assert the database stores HMAC rather than plaintext, reissue revokes earlier issued rows, retries do not create duplicate Keycloak users, bound users are rejected, errors omit secrets, and CSV data cells neutralize spreadsheet formula prefixes.

- [ ] **Step 2: Run red tests**

Run: python -m pytest apps/api/tests/test_keycloak_admin.py apps/api/tests/test_student_activations.py apps/api/tests/test_settings.py -q

Expected: FAIL because adapter, service, and new settings are absent.

- [ ] **Step 3: Implement minimal services**

Use target-realm client credentials. Keycloak adapter finds or creates username equal to school ID, writes school_id, assigns only student role, and sets temporary password. Lifecycle service locks student plus existing issued records, saves provisioning before external calls, saves HMAC/subject/expiry on success, records a bounded nonsensitive failure on error, and generates code with secrets.token_urlsafe(24). Production settings reject development defaults, empty provisioner secret, short HMAC key, invalid base URL, or non-positive expiry.

- [ ] **Step 4: Run green tests**

Run: python -m pytest apps/api/tests/test_keycloak_admin.py apps/api/tests/test_student_activations.py apps/api/tests/test_settings.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

Run: git add apps/api/src/edu_grader_api/settings.py apps/api/src/edu_grader_api/services/keycloak_admin.py apps/api/src/edu_grader_api/services/student_activations.py apps/api/tests/test_keycloak_admin.py apps/api/tests/test_student_activations.py apps/api/tests/test_settings.py

Run: git commit -m "feat: provision student activation codes"

### Task 3: Add teacher issuance and first-login lifecycle enforcement

**Files:**
- Modify: apps/api/src/edu_grader_api/routers/teacher.py
- Modify: apps/api/src/edu_grader_api/auth.py
- Modify: apps/api/tests/test_teacher_roster.py, apps/api/tests/test_auth.py, and apps/api/tests/test_student_activations.py

**Interfaces:**
- Batch route receives a list of student UUIDs for an owned class and returns CSV columns for status, name, school ID, code, expiry, and nonsensitive error.
- Roster rows expose account_state: unbound, activation_issued, or bound.
- Authentication consumes an unexpired issued activation exactly once, but denies an expired issued activation before returning a principal.

- [ ] **Step 1: Write failing route and login tests**

Test successful no-store attachment response, teacher/class isolation as 404, already-bound student as 409, partial failure CSV without code in errors, correct roster state, valid first login consuming activation, later login succeeding, and expired first login returning 403 with safe audit metadata.

- [ ] **Step 2: Run red tests**

Run: python -m pytest apps/api/tests/test_teacher_roster.py apps/api/tests/test_auth.py apps/api/tests/test_student_activations.py -q

Expected: FAIL because route, roster state, and auth gate are absent.

- [ ] **Step 3: Implement route and gate**

Use existing owned_class_or_404 and teacher role dependency. The response declares text/csv, Cache-Control no-store, and an attachment filename. After current roster identity binding or lookup, lock the issued activation. Mark unexpired state consumed and append ID-only audit data; append safe denial audit data and reject expired state. Users with no issued activation preserve current authentication behavior.

- [ ] **Step 4: Run green tests**

Run: python -m pytest apps/api/tests/test_teacher_roster.py apps/api/tests/test_auth.py apps/api/tests/test_student_activations.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

Run: git add apps/api/src/edu_grader_api/routers/teacher.py apps/api/src/edu_grader_api/auth.py apps/api/tests/test_teacher_roster.py apps/api/tests/test_auth.py apps/api/tests/test_student_activations.py

Run: git commit -m "feat: issue teacher student activation csv"

### Task 4: Add a one-response teacher download flow

**Files:**
- Modify: apps/web/app/lib/teacher-api.ts
- Modify: apps/web/app/pages/teacher/index.vue
- Modify: apps/web/server/api/core/[...path].ts
- Modify: apps/web/tests/teacher-api.test.ts and apps/web/tests/teacher-workbench.test.ts

**Interfaces:**
- downloadTeacherActivationCodes accepts CSRF token, class ID, and student IDs; returns an in-memory Blob plus attachment filename.
- UI permits selection and issuance only for unbound roster students.

- [ ] **Step 1: Write failing web tests**

Assert CSRF-protected POST body, the visible Chinese warning that downloaded codes cannot be viewed again, no bound-student action, attachment header forwarding, and retained no-store/cache-safe proxy behavior.

- [ ] **Step 2: Run red tests**

Run: npm test -- --run tests/teacher-api.test.ts tests/teacher-workbench.test.ts

Expected: FAIL because no helper, controls, warning, or header forwarding exists.

- [ ] **Step 3: Implement selection, confirmation, and Blob download**

Require confirmation before issuance. Use fetch with the existing BFF URL, read response as Blob, create a temporary object URL and click a download anchor, then revoke the URL immediately. Clear selection on success and display counts only. Never assign CSV content to reactive state, local storage, or IndexedDB. Proxy content-disposition in addition to content type while still stripping browser credential headers.

- [ ] **Step 4: Run green tests**

Run: npm test -- --run tests/teacher-api.test.ts tests/teacher-workbench.test.ts

Expected: PASS.

- [ ] **Step 5: Commit**

Run: git add apps/web/app/lib/teacher-api.ts apps/web/app/pages/teacher/index.vue apps/web/server/api/core/[...path].ts apps/web/tests/teacher-api.test.ts apps/web/tests/teacher-workbench.test.ts

Run: git commit -m "feat: download student activation codes"

### Task 5: Reconcile Keycloak and disable expired codes

**Files:**
- Create: apps/api/src/edu_grader_api/cli/reconcile_keycloak_realm.py
- Create: apps/api/src/edu_grader_api/cli/expire_student_activations.py
- Modify: infra/keycloak/edu-grader-realm.json, infra/k8s/production/realm.json, infra/k8s/production/application.yaml, infra/k8s/production/kustomization.yaml
- Create: infra/k8s/production/keycloak-realm-sync.yaml and infra/k8s/production/student-activation-expiry.yaml
- Modify: compose.yaml, .env.example, and apps/api/tests/test_settings.py

**Interfaces:**
- Realm sync is idempotent: school_id user profile permission, existing roles, mapper, provisioner client, client secret, and minimal realm-management mappings.
- Expiry CLI invokes Task 2 service. CronJob runs every five minutes.

- [ ] **Step 1: Write failing deployment and reconcile tests**

Assert API deployment has the provisioner secret but never bootstrap admin secret. Assert production realm contains school_id profile and student-provisioner client. Mock Admin API and prove a second reconcile call creates no duplicates. Assert only sync Job refers to admin password.

- [ ] **Step 2: Run red tests**

Run: python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_keycloak_admin.py -q

Expected: FAIL because realm client, jobs, and credential isolation are absent.

- [ ] **Step 3: Implement manifest and CLI isolation**

Replace API envFrom with explicit runtime settings and provisioner credential only. Sync Job receives bootstrap admin credentials and realm ConfigMap. Expiry CronJob receives database, activation HMAC, and provisioner settings only. Configure school_id profile admin write permission, confidential service-account provisioner, and only required user-query/user-management/role-read mappings. Include all resources in Kustomize. Local values are visibly development-only; no production value enters source.

- [ ] **Step 4: Run green configuration tests and render**

Run: python -m pytest apps/api/tests/test_settings.py apps/api/tests/test_keycloak_admin.py apps/api/tests/test_student_activations.py -q

Run: kubectl kustomize infra/k8s/production

Expected: PASS and rendered YAML contains API, sync Job, expiry CronJob, and no literal secrets.

- [ ] **Step 5: Commit**

Run: git add apps/api/src/edu_grader_api/cli infra/keycloak/edu-grader-realm.json infra/k8s/production compose.yaml .env.example apps/api/tests/test_settings.py

Run: git commit -m "feat: reconcile student provisioning realm"

### Task 6: Document and fully verify operations

**Files:**
- Modify: README.md
- Modify: apps/api/tests/test_settings.py
- Modify: docs/superpowers/plans/2026-07-26-student-activation-codes.md

- [ ] **Step 1: Write failing documentation test**

Assert README contains student-provisioner, the Chinese recovery term 重新签发, and 明文; do not test for or include a real secret value.

- [ ] **Step 2: Run red documentation test**

Run: python -m pytest apps/api/tests/test_settings.py -q

Expected: FAIL until safety and recovery instructions are written.

- [ ] **Step 3: Document operator procedure**

Document secret key names only, realm-sync ordering, one-time offline distribution, and reissue recovery. State that code and secret plaintext cannot enter source control, tickets, or logs.

- [ ] **Step 4: Run full verification**

Run: python -m pytest apps/api/tests/test_student_activations.py apps/api/tests/test_keycloak_admin.py apps/api/tests/test_teacher_roster.py apps/api/tests/test_auth.py apps/api/tests/test_settings.py -q

Run: python -m alembic -c apps/api/alembic.ini upgrade head

Run: python -m alembic -c apps/api/alembic.ini downgrade base

Run: python -m alembic -c apps/api/alembic.ini upgrade head

Run: cd apps/web; npm test; npm run build

Run: kubectl kustomize ../../infra/k8s/production

Expected: tests, migration round trip, web build, and rendered manifests all succeed.

- [ ] **Step 5: Commit**

Run: git add README.md docs/superpowers/plans/2026-07-26-student-activation-codes.md apps/api/tests/test_settings.py

Run: git commit -m "docs: explain student activation operations"

## Plan Self-Review

- Coverage: Tasks 1 through 3 implement lifecycle, temporary credentials, issuance, audit, expiry denial, and consumption. Task 4 delivers a one-time download. Task 5 handles current Keycloak reconciliation, secret separation, and expiry cleanup. Task 6 verifies and documents the workflow.
- Placeholder scan: clear; every implementation step has a concrete command and outcome.
- Interface consistency: Task 3 and Task 5 consume Task 2 KeycloakAdmin, issue_activations, and expire_activations. Task 4 consumes Task 3 endpoint and CSV response contract.
