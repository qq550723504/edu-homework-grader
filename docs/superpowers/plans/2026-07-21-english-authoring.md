# English Question Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Let teachers create valid E1–E4 questions through guided fields backed by an API-owned default-policy catalog, with E4@2 as the only new E4 policy.

**Architecture:** \`policies.py\` keeps the historical policy schema registry and adds a catalog of recommended defaults for new guided questions. The API exposes that catalog, but only rejects the explicitly retired E4@1 policy on create. The web app retrieves the catalog, maps guided English fields to existing \`CreateQuestionInput\`, and retains raw JSON only as an opt-in advanced mode.

**Tech Stack:** FastAPI, SQLAlchemy, JSON Schema, Nuxt 4 / Vue 3, TypeScript, Vitest, Playwright, pytest.

## Global Constraints

- Keep \`E4@1\` schema validation and historical records readable; reject it only for new question creation.
- Do not introduce a JSON Schema form dependency; the chosen Vue integration was evaluated as preview-only and mismatched to the existing renderer stack.
- Do not log question rules, answers, tokens, or identity information.
- Preserve the existing \`/v1/questions\` request payload and \`detail.errors\` 422 response shape.
- Every production behavior is introduced with a failing focused test before its implementation.

---

### Task 1: Establish the API-owned creation catalog and E4@1 creation guard

**Files:**

- Modify: \`apps/api/src/edu_grader_api/policies.py\`
- Modify: \`apps/api/src/edu_grader_api/routers/questions.py\`
- Modify: \`apps/api/src/edu_grader_api/services/questions.py\`
- Modify: \`apps/api/src/edu_grader_api/main.py\`
- Modify: \`apps/api/tests/test_english_policies.py\`
- Modify: \`apps/api/tests/test_questions.py\`

**Interfaces:**

- Produces \`question_policy_catalog() -> list[dict[str, str]]\` and \`validate_new_question_policy(question_type: str, policy_version: str) -> list[dict[str, str]]\`.
- Produces \`GET /v1/question-policy-catalog -> {"policies": list[dict[str, str]]}\` for authenticated teachers.
- \`create_question()\` calls \`validate_new_question_policy()\` before \`validate_policy()\`.

- [ ] **Step 1: Write the failing API tests.**

~~~python
def test_teacher_reads_the_question_creation_policy_catalog(client, session):
    teacher = User(tenant=Tenant(slug='pilot', name='Pilot'), role=Role.TEACHER,
                   oidc_issuer=ISSUER, oidc_subject='teacher', display_name='Teacher')
    session.add(teacher)
    session.commit()
    response = client.get('/v1/question-policy-catalog', headers=authorize(client, teacher))
    assert response.status_code == 200
    assert {'question_type': 'E4', 'policy_version': '2'} in response.json()['policies']
    assert {'question_type': 'E4', 'policy_version': '1'} not in response.json()['policies']

def test_question_creation_rejects_retired_e4_v1_but_schema_stays_read_compatible(client, session):
    teacher = User(tenant=Tenant(slug='pilot', name='Pilot'), role=Role.TEACHER,
                   oidc_issuer=ISSUER, oidc_subject='teacher', display_name='Teacher')
    session.add(teacher)
    session.commit()
    response = client.post('/v1/questions', headers=authorize(client, teacher), json={
        'title': 'Legacy E4', 'prompt': 'Explain.', 'question_type': 'E4',
        'policy_version': '1', 'rule': {'rubric': 'Legacy rubric'},
    })
    assert response.status_code == 422
    assert response.json()['detail']['errors'] == [
        {'path': '/', 'message': 'policy E4@1 cannot be used for new questions'}
    ]
    assert validate_policy('E4', '1', {'rubric': 'Legacy rubric'}) == []
~~~

- [ ] **Step 2: Run the focused tests and confirm they fail because no catalog route or creation guard exists.**

Run: \`pytest tests/test_english_policies.py tests/test_questions.py -q\`

Expected: failure on \`/v1/question-policy-catalog\` (404) and acceptance of E4@1 creation (201).

- [ ] **Step 3: Add the creation catalog and enforce it before schema validation.**

~~~python
DEFAULT_POLICY_KEYS = frozenset({
    ('M1', '1'), ('M2', '2'), ('E1', '2'), ('E2', '1'), ('E3', '1'), ('E4', '2'),
})

def question_policy_catalog() -> list[dict[str, str]]:
    return [
        {'question_type': question_type, 'policy_version': policy_version}
        for question_type, policy_version in sorted(DEFAULT_POLICY_KEYS)
    ]

def validate_new_question_policy(question_type: str, policy_version: str) -> list[dict[str, str]]:
    if (question_type, policy_version) != ('E4', '1'):
        return []
    return [{'path': '/', 'message': f'policy {question_type}@{policy_version} cannot be used for new questions'}]
~~~

Add a \`policy_catalog_router = APIRouter(prefix='/v1/question-policy-catalog', tags=['questions'])\` in \`routers/questions.py\`; import and include it from \`main.py\`. Import the creation helpers in \`services/questions.py\` and return the E4@1 creation error before normal schema validation without making the catalog a general allow-list.

- [ ] **Step 4: Run the focused API tests and format checks.**

Run: \`pytest tests/test_english_policies.py tests/test_questions.py -q && ruff check src tests\`

Expected: all focused tests pass and Ruff reports no findings.

- [ ] **Step 5: Commit the API slice.**

~~~powershell
git add apps/api/src/edu_grader_api/policies.py apps/api/src/edu_grader_api/routers/questions.py apps/api/src/edu_grader_api/services/questions.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_english_policies.py apps/api/tests/test_questions.py
git commit -m "feat(api): publish question creation policies"
~~~

### Task 2: Create a testable guided-English rule mapper

**Files:**

- Create: \`apps/web/app/lib/english-question-authoring.ts\`
- Create: \`apps/web/tests/english-question-authoring.test.ts\`

**Interfaces:**

- Produces \`defaultEnglishDraft(questionType: 'E1' | 'E2' | 'E3' | 'E4')\`.
- Produces \`buildEnglishQuestionRule(questionType, draft): { rule?: Record<string, unknown>; errors: Record<string, string> }\`.
- Produces \`fieldForPolicyError(path: string): string | null\`.

- [ ] **Step 1: Write failing mapper tests for each English policy and pointer mapping.**

~~~ts
it('builds an E4@2-compatible rule from scoring-point fields', () => {
  expect(buildEnglishQuestionRule('E4', {
    scoringPoints: [{ id: 'cause', evidencePhrases: ['bridge closed'], score: 1 }],
    similarityThreshold: 0.78, maxScore: 1,
  })).toEqual({
    rule: { scoring_points: [{ id: 'cause', evidence_phrases: ['bridge closed'], score: 1 }], similarity_threshold: 0.78, max_score: 1 },
    errors: {},
  })
})

it('maps API JSON Pointers to visible field keys', () => {
  expect(fieldForPolicyError('/scoring_points/0/evidence_phrases')).toBe('scoringPoints.0.evidencePhrases')
  expect(fieldForPolicyError('/')).toBeNull()
})
~~~

Include failing cases for E1 empty answers, E2 blank lemma, E3 missing grammar-feedback selection, E4 no scoring points, and non-finite/out-of-range numeric values.

- [ ] **Step 2: Run the mapper test and confirm the module cannot yet be imported.**

Run: \`npm test -- tests/english-question-authoring.test.ts\`

Expected: failure reporting that \`english-question-authoring.ts\` does not exist.

- [ ] **Step 3: Implement only the pure defaults, mapper, and error-path conversion.**

~~~ts
export function fieldForPolicyError(path: string): string | null {
  if (path === '/') return null
  return path
    .split('/').filter(Boolean)
    .map((segment) => ({ scoring_points: 'scoringPoints', evidence_phrases: 'evidencePhrases' }[segment] ?? segment))
    .join('.')
}
~~~

Have the mapper trim and deduplicate repeated text values, omit empty optional constraints, require finite scores, and return errors without throwing. Keep \`policy_version\` outside this module: it comes from Task 1's catalog.

- [ ] **Step 4: Run the mapper tests and the existing teacher workflow tests.**

Run: \`npm test -- tests/english-question-authoring.test.ts tests/teacher-workflow.test.ts\`

Expected: all tests pass.

- [ ] **Step 5: Commit the mapper slice.**

~~~powershell
git add apps/web/app/lib/english-question-authoring.ts apps/web/tests/english-question-authoring.test.ts
git commit -m "feat(web): map guided English question rules"
~~~

### Task 3: Connect the catalog and guided form to the teacher workspace

**Files:**

- Modify: \`apps/web/app/lib/teacher-api.ts\`
- Modify: \`apps/web/app/pages/teacher/index.vue\`
- Modify: \`apps/web/tests/teacher-api.test.ts\`
- Modify: \`apps/web/tests/teacher-workbench.test.ts\`

**Interfaces:**

- Produces \`fetchQuestionPolicyCatalog(request): Promise<QuestionPolicyCatalogEntry[]>\`.
- \`teacher/index.vue\` holds \`questionPolicies\` populated by \`loadWorkspace()\` and sends the catalog-selected version in \`CreateQuestionInput\`.
- The page exposes labelled guided inputs and an \`高级 JSON 模式\` checkbox.

- [ ] **Step 1: Write failing web API and page-contract tests.**

~~~ts
it('loads the API-owned policy catalog through the BFF', async () => {
  const request = vi.fn().mockResolvedValue({ policies: [{ question_type: 'E4', policy_version: '2' }] })
  await expect(fetchQuestionPolicyCatalog(request)).resolves.toEqual([{ question_type: 'E4', policy_version: '2' }])
  expect(request).toHaveBeenCalledWith('/api/core/v1/question-policy-catalog')
})

it('renders guided English inputs and hides raw JSON until advanced mode is selected', () => {
  const page = readFileSync(new URL('../app/pages/teacher/index.vue', import.meta.url), 'utf8')
  expect(page).toContain('可接受答案')
  expect(page).toContain('评分点')
  expect(page).toContain('高级 JSON 模式')
})
~~~

- [ ] **Step 2: Run the focused tests and confirm the catalog function and guided form are absent.**

Run: \`npm test -- tests/teacher-api.test.ts tests/teacher-workbench.test.ts\`

Expected: failure because \`fetchQuestionPolicyCatalog\` is not exported and expected labels are absent.

- [ ] **Step 3: Implement API client retrieval and the guided UI.**

Use \`Promise.all\` in \`loadWorkspace()\` to retrieve the catalog alongside workspace data. Select the matching catalog entry with:

~~~ts
const policy = questionPolicies.value.find((entry) => entry.question_type === question.question_type)
if (!policy) throw new Error(\`当前题型尚未开放：\${question.question_type}\`)
~~~

Render E1–E4 field sets with \`v-if\`, error text linked to visible inputs, add/remove controls for repeated answers and E4 points, and a form-level error for unknown JSON Pointer paths. In advanced mode, parse \`ruleJson\` with a user-facing parse error. Continue to use the existing generic controls for M1/M2.

- [ ] **Step 4: Run focused web tests and Nuxt production build.**

Run: \`npm test -- tests/english-question-authoring.test.ts tests/teacher-api.test.ts tests/teacher-workbench.test.ts && npm run build\`

Expected: all tests pass and Nuxt completes successfully.

- [ ] **Step 5: Commit the UI slice.**

~~~powershell
git add apps/web/app/lib/teacher-api.ts apps/web/app/pages/teacher/index.vue apps/web/tests/teacher-api.test.ts apps/web/tests/teacher-workbench.test.ts
git commit -m "feat(web): guide English question authoring"
~~~

### Task 4: Verify browser creation for E1–E4 and prevent regression

**Files:**

- Modify: \`apps/web/e2e/student-vertical-slice.spec.ts\`
- Modify: \`apps/api/tests/test_ci_e2e_workflow.py\` only if the new Playwright test needs an existing workflow allow-list or artifact declaration.

**Interfaces:**

- Adds a Playwright scenario that creates all four English draft types through \`/teacher#questions\`.
- Captures the E4 create request and asserts \`question_type === 'E4'\` and \`policy_version === '2'\`.

- [ ] **Step 1: Write the failing browser scenario.**

~~~ts
test('teacher creates guided E1 through E4 draft questions with the current policies', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(\`\${webBaseUrl}/teacher#questions\`)
  for (const scenario of [
    { type: 'E1', title: 'Browser E1', fill: () => page.getByLabel('可接受答案').fill('cat') },
    { type: 'E2', title: 'Browser E2', fill: async () => { await page.getByLabel('词元').fill('go'); await page.getByLabel('可接受词形').fill('went') } },
    { type: 'E3', title: 'Browser E3', fill: () => page.getByLabel('启用语法反馈').check() },
    { type: 'E4', title: 'Browser E4', fill: async () => { await page.getByLabel('评分点名称').fill('cause'); await page.getByLabel('证据短语').fill('bridge closed') } },
  ]) {
    await page.getByLabel('题型').selectOption(scenario.type)
    await page.getByLabel('题目标题').fill(scenario.title)
    await page.getByLabel('题干').fill('Answer the question.')
    await scenario.fill()
    const requestPromise = page.waitForRequest((request) => request.url().endsWith('/api/core/v1/questions') && request.method() === 'POST')
    await page.getByRole('button', { name: '创建草稿题目' }).click()
    if (scenario.type === 'E4') expect((await requestPromise).postDataJSON()).toMatchObject({ question_type: 'E4', policy_version: '2' })
    await expect(page.getByText('草稿题目已创建')).toBeVisible()
  }
})
~~~

The field labels used in this test are the exact accessible names introduced in Task 3; do not substitute CSS selectors.

- [ ] **Step 2: Run the single browser test and confirm it fails before the UI implementation is present.**

Run: \`npx playwright test e2e/student-vertical-slice.spec.ts --grep "guided E1 through E4"\`

Expected: failure because guided labels and/or the E4@2 request do not exist.

- [ ] **Step 3: Adjust only selectors or deterministic E2E fixtures required by the implemented UI.**

Do not add static grader behavior, private production routes, or browser-side policy-version overrides. Keep the existing isolated session and service-supervisor flow.

- [ ] **Step 4: Run the regression suite.**

Run: \`npm test && npm run test:e2e\`

Run: \`pytest tests/test_english_policies.py tests/test_questions.py tests/test_ci_e2e_workflow.py -q\`

Expected: all commands pass; the browser report demonstrates E1–E4 draft creation and E4@2 use.

- [ ] **Step 5: Commit the end-to-end coverage.**

~~~powershell
git add apps/web/e2e/student-vertical-slice.spec.ts apps/api/tests/test_ci_e2e_workflow.py
git commit -m "test: cover guided English authoring"
~~~
