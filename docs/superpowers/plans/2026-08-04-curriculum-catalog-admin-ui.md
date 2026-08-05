# Curriculum Catalog Administration UI Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a protected, import-first browser console for curriculum catalogue review and activation, reusing the existing governed curriculum API and lifecycle.

**Architecture:** Add administrator-only read endpoints for profiles and import batches, then use the existing same-origin Core API proxy. Build the surface under /platform/curriculum, which is already protected by the admin route middleware. Keep database validation, fingerprints, transactions, authorization, lifecycle transitions, and audit events in the API.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Nuxt 4, Vue 3, TypeScript, Vitest, Playwright.

## Global Constraints

- JSON and CSV use the existing ImportDocument; do not introduce a second catalogue format or data model.
- The persisted lifecycle remains draft -> in_review -> active, with retired for retirement.
- The importer cannot review or activate its own batch; backend authorization remains final.
- Teachers can read active curriculum only; draft and review data remain administrator-only.
- Dry-run is non-mutating and returns a catalogue fingerprint; creation submits that exact fingerprint.
- Active objective revisions remain immutable; changed objective content creates a new revision.
- Do not store textbook pages, credentials, student data, or copied curriculum text outside existing API payloads.
- Use the existing BFF route under /api/core/v1; do not add a second browser-to-API transport.
- Preserve unrelated working-tree changes and stage only files belonging to the current task.

---

### Task 1: Add administrator read APIs

Files:
- Modify: apps/api/src/edu_grader_api/routers/curriculum.py
- Modify: apps/api/src/edu_grader_api/services/curriculum_imports.py if shared query or serialization helpers are needed
- Test: apps/api/tests/test_curriculum_api.py

Interfaces:
- GET /v1/admin/curriculum/profiles?status=&limit=&offset= returns items, total, limit, offset.
- GET /v1/admin/curriculum/imports?status=&limit=&offset= returns paginated batch summaries.
- GET /v1/admin/curriculum/imports/{batch_id} returns batch status, summary, actors/timestamps, and normalized issues.
- All routes use require_curriculum_admin() and return the existing non-disclosing 404 for inaccessible records.

- [ ] Step 1: Write failing API tests.
  Create two profiles and batches with different statuses. Assert status filtering, limit/offset totals, issue locations, and teacher 404 responses.

  Example assertion:
  response = client.get("/v1/admin/curriculum/imports?status=draft&limit=1&offset=0", headers=headers("admin-token"))
  assert response.status_code == 200
  assert response.json()["total"] == 1
  assert len(response.json()["items"]) == 1

- [ ] Step 2: Run the failing tests.
  Command: set PYTHONPATH to apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src, then run python -m pytest apps/api/tests/test_curriculum_api.py -k "admin.*curriculum or curriculum.*import.*read" -q.
  Expected: FAIL because the read routes do not exist.

- [ ] Step 3: Implement the queries.
  Use SQLAlchemy status filters, deterministic ordering, select(func.count()) totals, and the existing batch issue relationship. Do not return raw source documents.

- [ ] Step 4: Verify.
  Run python -m pytest apps/api/tests/test_curriculum_api.py apps/api/tests/test_curriculum_imports.py -q with the same PYTHONPATH. Expected: targeted tests pass.

- [ ] Step 5: Commit only this slice.
  Stage the two API files and test file, then commit with message feat: expose curriculum administration read APIs.

### Task 2: Add typed browser helpers and the protected entry point

Files:
- Create: apps/web/app/lib/admin-curriculum.ts
- Create: apps/web/app/pages/platform/curriculum/index.vue
- Modify: apps/web/app/pages/platform/index.vue
- Test: apps/web/tests/admin-curriculum.test.ts

Interfaces:
- fetchAdminCurriculumProfiles(request, query) and fetchCurriculumImports(request, query) return paginated summaries.
- fetchCurriculumImport(request, batchId) returns batch detail and issues.
- fetchCurriculumImportSchema(request) returns the JSON schema and CSV columns.
- dryRunCurriculumImport(request, csrfToken, idempotencyKey, body) returns the analysis and fingerprint.
- createCurriculumImport(request, csrfToken, idempotencyKey, body) creates a draft using that fingerprint.

- [ ] Step 1: Write failing helper tests.
  Assert exact URL/query construction and that dry-run/create send X-CSRF-Token, Idempotency-Key, and the fingerprint. Test the query URL /api/core/v1/admin/curriculum/imports?status=draft&limit=20&offset=0.

- [ ] Step 2: Run the failing tests.
  In apps/web run npm test -- --run tests/admin-curriculum.test.ts.
  Expected: FAIL because the helper and route do not exist.

- [ ] Step 3: Implement.
  Follow admin-generation-defaults.ts for types and idempotency. Load profile and batch summaries, show an access-denied state, and link to import/detail routes. Add a curriculum link to the existing platform admin page.

- [ ] Step 4: Verify.
  In apps/web run npm test -- --run tests/admin-curriculum.test.ts tests/auth-routing.test.ts and npm run build. Expected: tests and build pass.

- [ ] Step 5: Commit only this slice.
  Stage the browser helper, route, platform link, and tests, then commit with message feat: add curriculum admin browser entry point.

### Task 3: Build the JSON/CSV import and dry-run workspace

Files:
- Create: apps/web/app/pages/platform/curriculum/import.vue
- Create: apps/web/app/components/admin/CurriculumImportWorkspace.vue
- Modify: apps/web/app/lib/admin-curriculum.ts
- Test: apps/web/tests/admin-curriculum-import.test.ts

Interfaces:
- The workspace owns format, metadata, grade mappings, and document text state.
- runDryRun() stores normalized_digest, catalogue_fingerprint, counts, conflicts, problems, and can_apply.
- createDraft() is enabled only when can_apply is true and sends the stored fingerprint.

- [ ] Step 1: Write failing component tests.
  Cover validation problems disabling creation, exact fingerprint reuse, stale-fingerprint 409 guidance, and separate JSON/CSV payload shapes.

- [ ] Step 2: Run the failing tests.
  In apps/web run npm test -- --run tests/admin-curriculum-import.test.ts.
  Expected: FAIL because the workspace does not exist.

- [ ] Step 3: Implement.
  Use a step layout for document input, dry-run result, and draft handoff. Render additions, updates, conflicts, and problems with JSON Pointer or row/column locations. Client parsing is only for display; the API remains authoritative.

- [ ] Step 4: Verify.
  In apps/web run npm test -- --run tests/admin-curriculum-import.test.ts. Expected: all import workspace tests pass.

- [ ] Step 5: Commit only this slice.
  Stage the import route, workspace, helper changes, and tests, then commit with message feat: add curriculum import dry-run workspace.

### Task 4: Build review, activation, export, and retirement views

Files:
- Create: apps/web/app/pages/platform/curriculum/imports/[batchId].vue
- Create: apps/web/app/pages/platform/curriculum/profiles/[profileCode].vue
- Create: apps/web/app/components/admin/CurriculumImportDetail.vue
- Create: apps/web/app/components/admin/CurriculumProfileDetail.vue
- Modify: apps/web/app/lib/admin-curriculum.ts
- Test: apps/web/tests/admin-curriculum-review.test.ts

Interfaces:
- Review actions call existing submit-review, review, and activate endpoints with CSRF and idempotency headers.
- Profile detail calls existing export and retirement-impact endpoints and requires confirmation before retirement.

- [ ] Step 1: Write failing review tests.
  Assert action availability for draft, in_review, active, and retired; disable importer self-review; require activation confirmation; render stable issue codes and locations; verify export and retirement URLs.

- [ ] Step 2: Run the failing tests.
  In apps/web run npm test -- --run tests/admin-curriculum-review.test.ts.
  Expected: FAIL because the detail views and action helpers do not exist.

- [ ] Step 3: Implement.
  Render server-returned actors, timestamps, and status. Refresh after transitions. Preserve the page on 409, show access-denied state on 403/404, and avoid duplicating writes after retryable failures.

- [ ] Step 4: Verify.
  In apps/web run npm test -- --run tests/admin-curriculum-review.test.ts and npm run build. Expected: tests and build pass.

- [ ] Step 5: Commit only this slice.
  Stage lifecycle pages, components, helper changes, and tests, then commit with message feat: add curriculum review and activation views.

### Task 5: Add E2E governance coverage and run the verification gate

Files:
- Create: apps/web/e2e/curriculum-admin.spec.ts
- Modify: apps/web/e2e/start-e2e-api.mjs only if a second admin identity is not exposed
- Modify: apps/api/src/edu_grader_api/e2e_support.py only if a dedicated import fixture is required

Interfaces:
- Use existing E2E platform-admin A/B identities for separation of duties and the teacher identity for read-only verification.
- Use the deterministic temporary SQLite supervisor; do not call a real curriculum source or OpenAI.

- [ ] Step 1: Write the browser E2E test.
  Cover: admin A dry-runs and creates a valid JSON draft; admin A cannot review or activate it; admin B reviews and activates it; teacher sees the active objective in AI generation but cannot access /platform/curriculum; a stale fingerprint is rejected without applying data.

- [ ] Step 2: Run the failing E2E test.
  In apps/web run npm.cmd run test:e2e -- e2e/curriculum-admin.spec.ts.
  Expected: FAIL because the routes are absent.

- [ ] Step 3: Implement only required fixture support.
  Use existing seed helpers and preserve source metadata, active revision, and authorization invariants. Do not weaken production validation or permissions.

- [ ] Step 4: Run the full verification gate.
  Run the curriculum API tests with the repository PYTHONPATH, then in apps/web run npm test, npm.cmd run test:e2e -- e2e/curriculum-admin.spec.ts e2e/teacher-ai-generation.spec.ts e2e/teacher-ai-review.spec.ts, and npm run build. Expected: all relevant checks pass; unrelated local-tool failures are reported separately.

- [ ] Step 5: Commit only E2E coverage.
  Stage the E2E spec and only changed fixture files, then commit with message test: cover curriculum catalogue administration flow.

## Plan Self-Review

- Import-first scope is covered by Tasks 2 and 3; no inline active-objective editor is introduced.
- Lifecycle, separation of duties, stale fingerprints, retirement confirmation, and teacher read-only behavior are covered by Tasks 1, 3, 4, and 5.
- The existing protected /platform namespace is preserved; no unprotected /admin route is added.
- The current backend gap, administrator profile and batch reads, is explicitly covered by Task 1.
- Every task names files, interfaces, tests, commands, and expected results; no placeholder steps remain.
