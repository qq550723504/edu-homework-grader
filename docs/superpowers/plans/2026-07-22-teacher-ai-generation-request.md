# 教师 AI 出题请求 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让教师依据当前课程目标创建受服务端约束、可审计且可立即审核的 AI 候选题批次。

**Architecture:** 保留既有课程 profile/grade/objective 读取端点，新增 tenant-scoped 额度投影，并将创建任务的课程、版本权威从浏览器收回服务端。Nuxt 使用独立创建页，纯 API 边界与状态组件分离；成功后跳转既有审核工作台而不复制审核逻辑。

**Tech Stack:** Python 3.14、FastAPI、Pydantic 2、SQLAlchemy、Nuxt 4、Vue 3、TypeScript、Vitest 4、Playwright。

## Global Constraints

- 浏览器只调用同源 `/api/core/v1/*`，所有写请求带 `X-CSRF-Token` 和一次用户操作一个的 `Idempotency-Key`。
- 公开创建 body 不含 `grade`、`subject`、`policy_catalog_version` 或 `prompt_version`；服务端从 active objective revision 与服务器拥有版本常量派生它们。
- `question_types` 长度严格等于 `requested_count`；每项必须在目标 revision 的 `allowed_question_types` 中。
- 额度为 UTC 日、tenant-scoped；`limits` 只是预检，创建时必须重新强制执行。
- 不显示或缓存 Provider 密钥、系统 Prompt、请求摘要、私有验证特征或教师约束历史；不编造费用金额或难度配比保证。
- 不实现单题重生成、批量接受或 Provider 级难度分配。

---

## File Structure

- Modify: `apps/api/src/edu_grader_api/routers/ai_question_generation.py` — 缩小公开创建 body、提供额度投影并保持重生成内部兼容。
- Modify: `apps/api/src/edu_grader_api/services/generation.py` — 服务端派生课程/版本快照并验证题型分配总数。
- Modify: `apps/api/tests/test_ai_question_generation_api.py` — 路由、配额、隔离与幂等回归。
- Modify: `apps/api/tests/test_generation_service.py` — 服务层派生与分配校验。
- Create: `apps/web/app/lib/teacher-ai-generation.ts` — 纯请求/类型/题型分配工具。
- Create: `apps/web/app/components/teacher/TeacherAiGenerationForm.vue` — 课程级联、分配与公开状态。
- Create: `apps/web/app/components/teacher/TeacherAiGenerationPage.vue` — CSRF、幂等键和成功导航协调。
- Create: `apps/web/app/pages/teacher/ai-questions/new.vue` — 独立教师创建页。
- Modify: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue` — 新批次入口。
- Create: `apps/web/tests/teacher-ai-generation.test.ts` — API 工具与分配单元测试。
- Create: `apps/web/tests/teacher-ai-generation-rendering.test.ts` — 表单级联和提交 DOM 测试。
- Modify: `apps/api/src/edu_grader_api/e2e_support.py` — 为 E2E tenant 提供 active curriculum profile/目标。
- Create: `apps/web/e2e/teacher-ai-generation.spec.ts` — 浏览器创建至审核页的纵向测试。

### Task 1: 收回生成任务的服务端权威并暴露额度

**Files:**
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_generation.py`
- Modify: `apps/api/src/edu_grader_api/services/generation.py`
- Test: `apps/api/tests/test_ai_question_generation_api.py`
- Test: `apps/api/tests/test_generation_service.py`

**Interfaces:**
- Produces `GET /v1/ai-question-generation/limits -> { max_batch_size, daily_tenant_limit, daily_used_count, remaining_count }`。
- Produces `POST /v1/ai-question-generation/jobs` body `{ curriculum_objective_revision_id, question_types, requested_count, teacher_constraint? }`。
- Produces an internal service constructor which derives grade, subject, catalog and prompt versions from server state before persistence.

- [ ] **Step 1: 写出失败的 API 与服务测试**

~~~python
def test_generation_create_derives_course_and_versions_from_the_active_objective(client, teacher_headers, active_objective):
    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers={**teacher_headers, "Idempotency-Key": "create-1"},
        json={"curriculum_objective_revision_id": str(active_objective.revision.id), "question_types": ["M1", "M1"], "requested_count": 2},
    )
    assert response.status_code == 201
    job = _stored_job(response.json()["id"])
    assert job.grade == active_objective.grade_mapping.internal_level
    assert job.subject == active_objective.subject

def test_generation_rejects_type_count_mismatch(client, teacher_headers, active_objective):
    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers={**teacher_headers, "Idempotency-Key": "count-mismatch"},
        json={"curriculum_objective_revision_id": str(active_objective.revision.id), "question_types": ["M1"], "requested_count": 2},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "generation_distribution_invalid"
~~~

- [ ] **Step 2: 确认新增测试因旧契约失败**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_service.py -q`

Expected: FAIL，旧 body 仍要求客户端 version/grade/subject，且 limits 路由不存在。

- [ ] **Step 3: 实现最小服务端契约**

~~~python
class CreateGenerationJobRequest(BaseModel):
    curriculum_objective_revision_id: UUID
    question_types: list[QuestionType] = Field(min_length=1, max_length=20)
    requested_count: int = Field(ge=1, le=20)
    teacher_constraint: str | None = Field(default=None, max_length=1_000)

def _generation_limits(session: Session, *, actor: User) -> dict[str, int]:
    used = _generation_count_since_utc_midnight(session, tenant_id=actor.tenant_id)
    limit = settings.generator_daily_tenant_limit
    return {"max_batch_size": settings.generator_max_batch_size, "daily_tenant_limit": limit, "daily_used_count": used, "remaining_count": max(limit - used, 0)}
~~~

Load the active revision before constructing the persisted job; reject a type/count mismatch with stable `GenerationServiceError`, derive `grade` and `subject` from the joined objective/mapping, and apply server-owned catalog constants. Keep regeneration on an internal constructor preserving its original snapshot.

- [ ] **Step 4: 确认 API 与服务回归通过**

Run: `python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_service.py -q`

Expected: PASS，包含新分配、派生、额度、配额、幂等和原有重生成测试。

- [ ] **Step 5: 提交**

~~~bash
git add apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/src/edu_grader_api/services/generation.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_service.py
git commit -m "feat: secure AI generation request contract"
~~~

### Task 2: 建立类型化教师端请求边界与表单页面

**Files:**
- Create: `apps/web/app/lib/teacher-ai-generation.ts`
- Create: `apps/web/app/components/teacher/TeacherAiGenerationForm.vue`
- Create: `apps/web/app/components/teacher/TeacherAiGenerationPage.vue`
- Create: `apps/web/app/pages/teacher/ai-questions/new.vue`
- Modify: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- Test: `apps/web/tests/teacher-ai-generation.test.ts`
- Test: `apps/web/tests/teacher-ai-generation-rendering.test.ts`

**Interfaces:**
- Consumes existing curriculum list endpoints and Task 1 limits/create endpoints。
- Produces `expandQuestionTypeCounts(counts: Record<TeacherAiQuestionType, number>): TeacherAiQuestionType[]` and `createAiGenerationJob(...)`。
- Emits `created(job: TeacherAiGenerationJob)` only after server creation succeeds。

- [ ] **Step 1: 写出失败的客户端与 DOM 测试**

~~~ts
it('expands type counts in stable type order and omits zero counts', () => {
  expect(expandQuestionTypeCounts({ M1: 2, M2: 0, E1: 1, E2: 0, E3: 0, E4: 0 })).toEqual(['M1', 'M1', 'E1'])
})

it('does not send browser-owned grade, subject or generation versions', async () => {
  const request = vi.fn().mockResolvedValue({ id: 'job-1', status: 'ready_for_review' })
  await createAiGenerationJob(request, 'csrf', 'key-1', { curriculum_objective_revision_id: 'objective-1', question_types: ['M1'], requested_count: 1 })
  expect(request).toHaveBeenCalledWith('/api/core/v1/ai-question-generation/jobs', expect.objectContaining({ body: { curriculum_objective_revision_id: 'objective-1', question_types: ['M1'], requested_count: 1 } }))
})
~~~

- [ ] **Step 2: 确认新增测试因模块/组件不存在而失败**

Run: `cd apps/web && npm test -- --run tests/teacher-ai-generation.test.ts tests/teacher-ai-generation-rendering.test.ts`

Expected: FAIL，因为生成模块、表单和创建页尚不存在。

- [ ] **Step 3: 实现请求函数和受控级联表单**

~~~ts
export function createAiGenerationJob(request: Request, csrfToken: string, key: string, body: CreateAiGenerationJobInput) {
  return request<TeacherAiGenerationJob>('/api/core/v1/ai-question-generation/jobs', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
    body,
  })
}

export function expandQuestionTypeCounts(counts: Record<TeacherAiQuestionType, number>): TeacherAiQuestionType[] {
  return QUESTION_TYPES.flatMap((type) => Array.from({ length: counts[type] }, () => type))
}
~~~

Fetch child catalog data only after its parent is selected. Reset every dependent selection before a child request, guard responses with a monotonic request generation, and show only the chosen revision's allowed types and true difficulty range. The page obtains CSRF from the current session, holds a key until definitive response or input edit, then calls `navigateTo({ path: '/teacher/ai-questions', query: { job: job.id } })`. Add a visible link to `/teacher/ai-questions/new` from the review workspace.

- [ ] **Step 4: 确认前端定向测试通过**

Run: `cd apps/web && npm test -- --run tests/teacher-ai-generation.test.ts tests/teacher-ai-generation-rendering.test.ts tests/teacher-ai-review-rendering.test.ts`

Expected: PASS，覆盖分配、请求头/body、级联重置、额度禁用、允许题型、公开错误与成功导航。

- [ ] **Step 5: 提交**

~~~bash
git add apps/web/app/lib/teacher-ai-generation.ts apps/web/app/components/teacher/TeacherAiGenerationForm.vue apps/web/app/components/teacher/TeacherAiGenerationPage.vue apps/web/app/pages/teacher/ai-questions/new.vue apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/tests/teacher-ai-generation.test.ts apps/web/tests/teacher-ai-generation-rendering.test.ts
git commit -m "feat: add teacher AI generation request form"
~~~

### Task 3: 覆盖创建到审核的真实浏览器链路

**Files:**
- Modify: `apps/api/src/edu_grader_api/e2e_support.py`
- Create: `apps/web/e2e/teacher-ai-generation.spec.ts`
- Test: `apps/web/e2e/teacher-ai-generation.spec.ts`

**Interfaces:**
- Consumes E2E teacher authentication, active curriculum seed, fake generation provider and `/teacher/ai-questions/new`。
- Produces a browser assertion that the newly created server job is selected in the existing review workspace。

- [ ] **Step 1: 写出失败的 Playwright 测试**

~~~ts
test('teacher creates a curriculum-bound AI batch and lands in its review workspace', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions/new`)
  await page.getByLabel('课程标准').selectOption({ label: /E2E Curriculum/ })
  await page.getByLabel('年级').selectOption('G7')
  await page.getByLabel('学科').selectOption('Mathematics')
  await page.getByLabel('教学目标').selectOption({ label: /Fractions/ })
  await page.getByRole('button', { name: 'M1 增加数量' }).click()
  await page.getByRole('button', { name: '创建候选题批次' }).click()
  await expect(page).toHaveURL(/\/teacher\/ai-questions\?job=/)
  await expect(page.getByText('候选题 1')).toBeVisible()
})
~~~

- [ ] **Step 2: 确认 E2E 测试因创建页不存在而失败**

Run: `cd apps/web && npm run test:e2e -- --grep "curriculum-bound AI batch"`

Expected: FAIL，因为创建页和稳定课程种子尚未存在。

- [ ] **Step 3: 增加幂等种子和稳定浏览器选择器**

In `seed_e2e_data`, create one active profile, `G7` grade mapping and a Mathematics objective revision with `M1` allowed. Reuse stable codes and query before creating, so repeated local runs do not create duplicates. Do not seed a job: the test must invoke the real creation route. Use labels and roles before `data-testid`.

- [ ] **Step 4: 确认 E2E 通过并执行相关回归**

Run: `cd apps/web && npm run test:e2e -- --grep "AI (candidates|batch)"`

Expected: PASS，既有审核和新建批次浏览器用例都通过。

- [ ] **Step 5: 提交**

~~~bash
git add apps/api/src/edu_grader_api/e2e_support.py apps/web/e2e/teacher-ai-generation.spec.ts
git commit -m "test: cover teacher AI generation request flow"
~~~

### Task 4: 完整验证、审查与交付记录

**Files:**
- Modify: `docs/superpowers/plans/2026-07-22-teacher-ai-generation-request.md` — 勾选已验证步骤并记录实际命令/结果。

**Interfaces:**
- Consumes Tasks 1–3。
- Produces可审计验证记录和一个先创建为草稿的 GitHub PR。

- [ ] **Step 1: 执行完整质量门禁**

Run:

~~~bash
make api-test
make api-lint
make web-test
make web-build
make web-e2e
~~~

Expected: 每个命令 exit 0；仅记录已知、无功能影响的构建警告，不把它们误报为通过条件。

- [ ] **Step 2: 检查实现与文档边界**

Run:

~~~bash
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
rg -n "policy_catalog_version|prompt_version|grade:|subject:" apps/web/app/lib/teacher-ai-generation.ts apps/web/app/components/teacher/TeacherAiGenerationForm.vue
~~~

Expected: diff check 无输出；最后一条不显示浏览器拥有的旧创建字段。

- [ ] **Step 3: 请求独立代码审查并修复 Critical/Important 项**

Review requirements: 服务端派生课程/版本、配额竞争安全、幂等不变、页面不泄露私有数据、级联并发不覆盖较新选择、E2E 真实调用创建路由。修复任何 Critical/Important 项后重跑受影响测试和完整门禁。

- [ ] **Step 4: 创建草稿 PR，等待所有检查，再合并**

~~~bash
git push -u origin codex/teacher-ai-generation-request
gh pr create --draft --base main --head codex/teacher-ai-generation-request --title "feat: add teacher AI generation request form"
gh pr checks --watch
gh pr ready <number>
gh pr merge <number> --squash --delete-branch
~~~

Expected: 草稿 PR 先于合并创建；required checks 全绿后才转 ready 并 squash merge。#41 的重生成和批量接受未完成时保持 open。
