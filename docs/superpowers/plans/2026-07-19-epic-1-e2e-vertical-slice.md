# Epic #1 End-to-End Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable API and browser acceptance path for the teacher-to-student mathematics workflow in Epic #1.

**Architecture:** A new Python HTTP acceptance test drives the existing public routes from question creation through correction publication with deterministic in-process grader doubles. A separate, loopback-only E2E ASGI entrypoint seeds fictional data and accepts fixed test identities, allowing Playwright to exercise the Nuxt student pages against a real API while leaving production authentication untouched.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Playwright, Nuxt 4, Vitest, SQLite, Node.js.

## Global Constraints

- The production `edu_grader_api.main:app` must not accept any E2E bearer token or import the E2E application.
- All role transitions in the API acceptance test must use public HTTP endpoints; do not create domain rows to skip a transition.
- Browser fixtures use only fictional names, school IDs, prompts, and answers.
- Playwright runs Chromium only and fails when API or Nuxt cannot start; it must not skip unavailable services.
- Existing `python -m pytest`, `npm test`, Compose, and OIDC behavior remain unchanged.

---

## File Structure

- `apps/api/tests/test_epic_1_e2e.py`: API-only vertical acceptance test plus local fixtures and deterministic grader double.
- `apps/api/src/edu_grader_api/e2e_app.py`: test-only FastAPI application factory, temporary SQLite setup, fictional tenant seed, and static token verifier.
- `apps/api/src/edu_grader_api/e2e_support.py`: shared E2E constants, seed result, deterministic M2 normalizer/grader, and explicit cleanup helpers.
- `apps/web/app/pages/student/assignments/[assignmentId].vue`: render published student-safe feedback and correction availability after reload.
- `apps/web/tests/student-assignment-feedback.test.ts`: unit test the presentation mapper used by the student page.
- `apps/web/app/lib/student-api.ts`: typed projection helpers for published grading and correction information.
- `apps/web/playwright.config.ts`: Chromium-only Playwright configuration and managed API/Nuxt web servers.
- `apps/web/e2e/start-e2e-api.mjs`: creates a unique temporary SQLite path, launches the loopback E2E API, and removes the database when the child exits.
- `apps/web/e2e/student-vertical-slice.spec.ts`: student-browser acceptance test, teacher-side REST setup, and trace assertions.
- `apps/web/package.json` and `apps/web/package-lock.json`: Playwright dependency and `test:e2e` command.
- `README.md`: first-run browser install and repeatable E2E command.

## Task 1: API vertical acceptance test

**Files:**
- Create: `apps/api/tests/test_epic_1_e2e.py`
- Modify: `apps/api/tests/test_question_runs.py` only if a reusable fake-grade response must be exported; otherwise keep the test double local.

**Interfaces:**
- Consumes: public routes under `/v1/questions`, `/v1/question-versions`, `/v1/assignments`, `/v1/student`, `/v1/review-tasks`, and `/v1/appeals`.
- Produces: `test_teacher_to_student_correction_vertical_slice(client, session, monkeypatch)` proving the complete acceptance path.

- [ ] **Step 1: Write the failing endpoint-driven test**

```python
def test_teacher_to_student_correction_vertical_slice(client, session, monkeypatch) -> None:
    teacher, student, classroom = seed_teacher_student_classroom(session)
    install_deterministic_m2_grader(monkeypatch)

    draft = client.post("/v1/questions", headers=auth(client, teacher), json={...})
    version_id = draft.json()["version_id"]
    for case in M2_CASES:
        assert client.post(f"/v1/question-versions/{version_id}/test-cases", ...).status_code == 201
    assert client.post(f"/v1/question-versions/{version_id}/test-runs", ...).status_code == 201
    assert client.post(f"/v1/question-versions/{version_id}/publish", ...).status_code == 200

    assignment_id = create_and_publish_assignment(client, teacher, classroom, version_id)
    attempt_id, item_id = open_assignment(client, student, assignment_id)
    assert save_mathjson_answer(client, student, attempt_id, item_id).status_code == 200
    submitted = submit_once(client, student, assignment_id)
    assert submitted.status_code == 200
    assert publish_after_teacher_confirmation(client, teacher, assignment_id, attempt_id).status_code == 201
    assert correction_round_trip(client, teacher, student, assignment_id, attempt_id).status_code == 201
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/api/tests/test_epic_1_e2e.py -q`

Expected: FAIL because the acceptance test and route-driving helpers do not exist.

- [ ] **Step 3: Implement the minimal test fixtures and deterministic double**

```python
class DeterministicM2Client:
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        return {"kind": "symbol", "value": "x_plus_1"}

    def grade(self, question_type: str, rule_json: dict[str, object], answer_json: dict[str, object], *, policy_version: str | None = None) -> GradeResult:
        assert question_type == "M2" and policy_version == "2"
        return GradeResult(
            decision="correct", score=4.0, grader_version="e2e-m2@1",
            evidence={"max_score": 4, "confidence": 1.0, "requires_review": True,
                      "criteria": [{"code": "algebraic_equivalence", "passed": True, "score": 4, "max_score": 4}],
                      "feedback": [{"type": "result", "message": "表达式等价。"}],
                      "dependency_versions": {"grader": "e2e-m2@1"}},
        )
```

Monkeypatch every HTTP-route import site that constructs `HttpGraderClient` so test-case execution, MathJSON normalization, submission, and review reruns use the same deterministic double. Assert the persisted `GradingRun` contains the question-version ID, policy version `2`, grader version `e2e-m2@1`, and criterion evidence; assert student detail does not expose rule snapshots before publication and does expose only student-safe feedback after it.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest apps/api/tests/test_epic_1_e2e.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the API acceptance slice**

```bash
git add apps/api/tests/test_epic_1_e2e.py
git commit -m "test: cover epic 1 API vertical slice"
```

## Task 2: Isolated E2E API process

**Files:**
- Create: `apps/api/src/edu_grader_api/e2e_support.py`
- Create: `apps/api/src/edu_grader_api/e2e_app.py`
- Test: `apps/api/tests/test_e2e_app.py`

**Interfaces:**
- Consumes: `Base`, `get_session`, `get_token_verifier`, existing routers, and the deterministic M2 result contract from Task 1.
- Produces: `app` export from `edu_grader_api.e2e_app`; `STUDENT_TOKEN`, `TEACHER_TOKEN`, and `seed_demo_assignment(session)` from `e2e_support`.

- [ ] **Step 1: Write failing safety and seed tests**

```python
def test_e2e_app_accepts_only_its_static_fictional_tokens(tmp_path, monkeypatch) -> None:
    client = e2e_client(tmp_path, monkeypatch)
    assert client.get("/v1/me", headers=bearer(STUDENT_TOKEN)).status_code == 200
    assert client.get("/v1/me", headers=bearer("production-token")).status_code == 401

def test_production_app_does_not_accept_e2e_token(client) -> None:
    assert client.get("/v1/me", headers=bearer(STUDENT_TOKEN)).status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest apps/api/tests/test_e2e_app.py -q`

Expected: FAIL because the E2E application and its token constants do not exist.

- [ ] **Step 3: Implement a separate app factory and temporary database lifecycle**

```python
# e2e_app.py
from .main import app as production_app

app = FastAPI(title="Edu Homework Grader E2E API")
for route in production_app.router.routes:
    app.router.routes.append(route)

app.dependency_overrides[get_token_verifier] = lambda: StaticE2EVerifier()
app.dependency_overrides[get_session] = e2e_session

@app.on_event("startup")
def seed() -> None:
    Base.metadata.create_all(E2E_ENGINE)
    seed_demo_assignment(Session(E2E_ENGINE))
```

Use a database URL supplied only by `E2E_DATABASE_URL`; reject a missing value and reject URLs that are not `sqlite` or are not beneath the process temporary directory. Bind the server only through Playwright's `127.0.0.1` command. The verifier maps exactly `e2e-student-token` and `e2e-teacher-token` to fixed issuer/subject pairs. Do not add a test-mode setting, route, or token handling to `main.py`.

- [ ] **Step 4: Run focused safety tests**

Run: `python -m pytest apps/api/tests/test_e2e_app.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the test-only server**

```bash
git add apps/api/src/edu_grader_api/e2e_support.py apps/api/src/edu_grader_api/e2e_app.py apps/api/tests/test_e2e_app.py
git commit -m "test: add isolated e2e api app"
```

## Task 3: Student feedback and correction projection

**Files:**
- Modify: `apps/web/app/lib/student-api.ts`
- Modify: `apps/web/app/pages/student/assignments/[assignmentId].vue`
- Create: `apps/web/tests/student-assignment-feedback.test.ts`

**Interfaces:**
- Consumes: assignment-detail response fields `grading` and `corrections` already emitted by the student API after publication.
- Produces: `publishedFeedback(detail)` returning only safe feedback messages and `correctionAvailable(detail)` returning a boolean; page copy with stable roles for Playwright.

- [ ] **Step 1: Write failing projection tests**

```ts
it('returns messages only after the API supplies published grading', () => {
  expect(publishedFeedback({ grading: [] })).toEqual([])
  expect(publishedFeedback({ grading: [{ feedback: [{ message: '表达式等价。' }] }] }))
    .toEqual(['表达式等价。'])
})

it('reports correction availability only for published correction rows', () => {
  expect(correctionAvailable({ corrections: [] })).toBe(false)
  expect(correctionAvailable({ corrections: [{ status: 'published' }] })).toBe(true)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- --run tests/student-assignment-feedback.test.ts`

Expected: FAIL because the projection helpers do not exist.

- [ ] **Step 3: Add typed, student-safe render helpers and page markup**

```ts
export function publishedFeedback(detail: { grading?: Array<{ feedback?: Array<{ message?: string }> }> }): string[] {
  return (detail.grading ?? []).flatMap((run) => (run.feedback ?? [])
    .flatMap((entry) => typeof entry.message === 'string' ? [entry.message] : []))
}

export function correctionAvailable(detail: { corrections?: Array<{ status?: string }> }): boolean {
  return (detail.corrections ?? []).some((entry) => entry.status === 'published')
}
```

Render `<section aria-label="已发布反馈">` only when feedback exists, and `<p role="status">可以查看订正结果</p>` only when `correctionAvailable(detail)` is true. Keep answer JSON, score-rule snapshots, criteria, and teacher-only evidence out of the page types and template.

- [ ] **Step 4: Run focused Web tests**

Run: `npm test -- --run tests/student-assignment-feedback.test.ts tests/student-api.test.ts`

Expected: both files pass.

- [ ] **Step 5: Commit the student projection**

```bash
git add apps/web/app/lib/student-api.ts apps/web/app/pages/student/assignments/[assignmentId].vue apps/web/tests/student-assignment-feedback.test.ts
git commit -m "feat(web): show published assignment feedback"
```

## Task 4: Playwright browser acceptance command

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/e2e/start-e2e-api.mjs`
- Create: `apps/web/e2e/student-vertical-slice.spec.ts`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2 `edu_grader_api.e2e_app:app`, `STUDENT_TOKEN`, `TEACHER_TOKEN`, and Task 3's accessible feedback/correction copy.
- Produces: `npm run test:e2e` that starts API and Nuxt, runs Chromium, and retains failure traces in `apps/web/test-results/`.

- [ ] **Step 1: Write the failing Playwright test and script entry**

```ts
test('student submits an algebra answer and sees published feedback', async ({ page, request }) => {
  await page.context().addCookies([{ name: 'edu_access_token', value: STUDENT_TOKEN, url: webBaseUrl }])
  await page.goto(`${webBaseUrl}/student`)
  await expect(page.getByRole('link', { name: '进入作答' })).toBeVisible()
  await page.getByRole('link', { name: '进入作答' }).click()
  await page.getByLabel('数学答案').fill('x+1')
  await expect(page.getByText('同步状态：已同步')).toBeVisible()
  await page.getByRole('button', { name: '提交作业' }).click()
  await expect(page.getByText('同步状态：已提交')).toBeVisible()
  await publishWithTeacher(request)
  await page.reload()
  await expect(page.getByRole('region', { name: '已发布反馈' })).toContainText('表达式等价。')
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm run test:e2e`

Expected: FAIL because Playwright, its config, the E2E process, and the browser test are absent.

- [ ] **Step 3: Install and configure Playwright without replacing existing test tooling**

Run `npm install --save-dev @playwright/test` from `apps/web`; retain the lockfile-resolved version and add `"test:e2e": "playwright test"` alongside the existing `test` script.

Configure exactly two `webServer` commands: `node e2e/start-e2e-api.mjs` and `npm run dev -- --port 13000` with `NUXT_PUBLIC_API_BASE=http://127.0.0.1:18000`. `start-e2e-api.mjs` creates a database path beneath `os.tmpdir()`, sets `E2E_DATABASE_URL` for `python -m uvicorn edu_grader_api.e2e_app:app --host 127.0.0.1 --port 18000`, forwards termination signals, and removes the SQLite file only after the child process exits. Use `reuseExistingServer: false`, Chromium only, `trace: 'retain-on-failure'`, `screenshot: 'only-on-failure'`, and `video: 'retain-on-failure'`. The Playwright test's teacher REST helper authenticates with `TEACHER_TOKEN`, confirms the deterministic review task, publishes results, approves the student's appeal, and publishes the correction; it never calls a private E2E HTTP route.

- [ ] **Step 4: Document first-run and regular commands**

```markdown
cd apps/web
npx playwright install chromium
npm run test:e2e
```

State that the command starts a temporary local API with fictional seeded data and does not verify production Keycloak login.

- [ ] **Step 5: Run all affected test suites**

Run: `python -m pytest apps/api/tests/test_epic_1_e2e.py apps/api/tests/test_e2e_app.py -q; npm test; npm run test:e2e`

Expected: all commands exit 0; Playwright reports one Chromium test passed.

- [ ] **Step 6: Commit browser acceptance support**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/playwright.config.ts apps/web/e2e/start-e2e-api.mjs apps/web/e2e/student-vertical-slice.spec.ts README.md
git commit -m "test(web): add student e2e acceptance"
```

## Task 5: Full regression and handoff

**Files:**
- Modify only if verification identifies a scoped defect in the files above.

**Interfaces:**
- Consumes: Tasks 1 through 4.
- Produces: verified implementation with no uncommitted files.

- [ ] **Step 1: Run Python quality checks**

Run: `python -m pytest apps/api/tests packages/processor-policy/tests services/grader/tests -q; python -m ruff check apps/api services/grader packages/processor-policy; python -m ruff format --check apps/api/src/edu_grader_api/e2e_app.py apps/api/src/edu_grader_api/e2e_support.py apps/api/tests/test_epic_1_e2e.py apps/api/tests/test_e2e_app.py`

Expected: all commands exit 0.

- [ ] **Step 2: Run Web quality checks**

Run: `npm test; npm run test:e2e`

Expected: Vitest and one Chromium Playwright scenario pass.

- [ ] **Step 3: Inspect final repository state**

Run: `git status --short --branch; git log --oneline -5`

Expected: clean feature branch containing focused commits from Tasks 1 through 4.

- [ ] **Step 4: Commit any scoped verification fix**

```bash
git status --short
git add apps/api/src/edu_grader_api/e2e_app.py apps/api/src/edu_grader_api/e2e_support.py apps/api/tests/test_epic_1_e2e.py apps/api/tests/test_e2e_app.py apps/web/app/lib/student-api.ts apps/web/app/pages/student/assignments/[assignmentId].vue apps/web/tests/student-assignment-feedback.test.ts apps/web/package.json apps/web/package-lock.json apps/web/playwright.config.ts apps/web/e2e/start-e2e-api.mjs apps/web/e2e/student-vertical-slice.spec.ts README.md
git commit -m "fix: stabilize epic 1 e2e acceptance"
```

Only create this commit when a verification defect required a source change; otherwise leave the prior focused commits unchanged.
