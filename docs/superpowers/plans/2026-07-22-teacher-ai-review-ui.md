# 教师 AI 候选题审核界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让教师在独立 Web 工作台中查看 AI 批次、检查验证证据、编辑/拒绝/接受候选题，并只把接受结果带入既有草稿题库流程。

**Architecture:** 新增独立 `/teacher/ai-questions` 路由和三个职责单一的 Vue 组件。`teacher-ai-review.ts` 是唯一的 BFF 请求边界，页面只投影 API 的当前修订与净化验证证据；每次写操作由页面生成并持有一个 `Idempotency-Key`。不改变审核 API、Provider 或题库发布状态机。

**Tech Stack:** Nuxt 4、Vue 3 Composition API、TypeScript、Vitest 4、@vue/test-utils、happy-dom、Playwright。

## Global Constraints

- 只调用同源 `/api/core/v1/*`；不在浏览器读取、缓存或显示模型密钥、系统 Prompt、教师约束、请求摘要或私有验证特征。
- 所有写请求同时发送 `X-CSRF-Token` 和一次操作一个的 `Idempotency-Key`；服务端审核修订号是唯一并发权威。
- `objective_revision_id`、`question_type`、`policy_version` 在 UI 永远只读，保存时从当前服务端候选复制。
- `blocked` 永不允许接受；`warning` 必须勾选确认；接受只产生 `QuestionVersion(status=draft)`，不发布。
- 小屏先显示批次列表再显示详情；不使用固定宽度造成横向滚动。
- 不实现生成表单、成本估算、重生成、批量接受或轮询。

---

## File Structure

- Create: `apps/web/app/lib/teacher-ai-review.ts` — API 类型、请求函数、候选编辑校验与公开错误映射。
- Create: `apps/web/app/components/teacher/TeacherAiJobList.vue` — 只显示并选择生成批次。
- Create: `apps/web/app/components/teacher/TeacherAiCandidateReview.vue` — 候选编辑、验证证据与接受/拒绝交互。
- Create: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue` — URL 同步、加载、会话 CSRF、写操作和刷新。
- Create: `apps/web/app/pages/teacher/ai-questions.vue` — 教师工作台壳与新工作区入口。
- Modify: `apps/web/app/lib/teacher-workbench.ts` — 增加 `ai_questions` 模块。
- Modify: `apps/web/app/components/teacher/TeacherWorkbenchNav.vue` — 新模块使用独立 URL。
- Create: `apps/web/tests/teacher-ai-review.test.ts` — 请求/校验/状态机单元测试。
- Create: `apps/web/tests/teacher-ai-review-rendering.test.ts` — happy-dom 组件交互测试。
- Create: `apps/web/e2e/teacher-ai-review.spec.ts` — 已有 fake Provider 批次的浏览器审核切片。
- Modify: `apps/api/src/edu_grader_api/e2e_support.py` — 为现有教师 E2E 身份种入一个通过验证、一个 warning/blocked 的可审核候选批次；只用于 `E2E_MODE`。

### Task 1: 建立类型化审核 BFF 边界和导航

**Files:**
- Create: `apps/web/app/lib/teacher-ai-review.ts`
- Modify: `apps/web/app/lib/teacher-workbench.ts`
- Modify: `apps/web/app/components/teacher/TeacherWorkbenchNav.vue`
- Test: `apps/web/tests/teacher-ai-review.test.ts`

**Interfaces:**
- Produces `fetchAiGenerationJobs`, `fetchAiGenerationDrafts`, `saveAiCandidateRevision`, `rejectAiCandidate`, `acceptAiCandidate`, `candidateEditInput`, `canAcceptCandidate`.
- Produces `TeacherAiGenerationJob`, `TeacherAiDraft`, `TeacherAiCandidate`, `TeacherAiValidationRun` and `TeacherAiReviewDecision` for Tasks 2–4.

- [ ] **Step 1: 写出失败的请求与状态测试**

```ts
it('sends a revision with CSRF, idempotency key and the immutable candidate fields', async () => {
  const request = vi.fn().mockResolvedValue({ draft_id: 'draft-1', revision_number: 2, validation_run: passedRun })
  await saveAiCandidateRevision(request, 'csrf', 'draft-1', 'key-1', 1, candidate)
  expect(request).toHaveBeenCalledWith('/api/core/v1/ai-generated-questions/draft-1/revisions', {
    method: 'POST', headers: { 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'key-1' },
    body: { expected_revision_number: 1, candidate },
  })
})

it('requires warning confirmation and rejects blocked candidates', () => {
  expect(canAcceptCandidate({ teacher_state: 'pending_review', validation: blockedRun, warningConfirmed: true })).toBe(false)
  expect(canAcceptCandidate({ teacher_state: 'pending_review', validation: warningRun, warningConfirmed: false })).toBe(false)
  expect(canAcceptCandidate({ teacher_state: 'pending_review', validation: warningRun, warningConfirmed: true })).toBe(true)
})
```

- [ ] **Step 2: 确认测试失败**

Run: `npm test -- --run tests/teacher-ai-review.test.ts`

Expected: FAIL，因为模块和导出尚不存在。

- [ ] **Step 3: 实现 API 模块、校验与导航**

```ts
export function saveAiCandidateRevision(request: Request, csrfToken: string, draftId: string, key: string, expectedRevisionNumber: number, candidate: TeacherAiCandidate) {
  return request<TeacherAiRevisionResult>(`/api/core/v1/ai-generated-questions/${draftId}/revisions`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
    body: { expected_revision_number: expectedRevisionNumber, candidate },
  })
}

export function canAcceptCandidate(input: { teacher_state: string; validation: TeacherAiValidationRun | null; warningConfirmed: boolean }) {
  return input.teacher_state === 'pending_review'
    && input.validation?.status !== 'blocked'
    && (input.validation?.status !== 'warning' || input.warningConfirmed)
}
```

Add `{ id: 'ai_questions', label: 'AI 出题审核' }` to `teacherModules`, include it in `TeacherModule`, and return `'/teacher/ai-questions'` from `destination`.

- [ ] **Step 4: 确认单元测试通过**

Run: `npm test -- --run tests/teacher-ai-review.test.ts tests/teacher-workbench.test.ts`

Expected: PASS，断言 URL、请求头、不可变字段保留、JSON/E4/难度校验和审核状态映射。

- [ ] **Step 5: 提交**

```bash
git add apps/web/app/lib/teacher-ai-review.ts apps/web/app/lib/teacher-workbench.ts apps/web/app/components/teacher/TeacherWorkbenchNav.vue apps/web/tests/teacher-ai-review.test.ts apps/web/tests/teacher-workbench.test.ts
git commit -m "feat: add teacher AI review API client"
```

### Task 2: 实现批次列表与候选审核组件

**Files:**
- Create: `apps/web/app/components/teacher/TeacherAiJobList.vue`
- Create: `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- Test: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes Task 1 的 `TeacherAiGenerationJob`, `TeacherAiDraft`, `TeacherAiValidationRun`, `canAcceptCandidate`。
- Produces `select-job`, `save-revision`, `reject`, `accept` 事件；Task 3 负责真实请求。

- [ ] **Step 1: 写出失败的 DOM 测试**

```ts
it('renders E4 material and blocks acceptance until warning confirmation', async () => {
  const wrapper = mount(TeacherAiCandidateReview, { props: { draft: warningE4Draft, busy: false } })
  expect(wrapper.get('[data-testid="reading-material"]').text()).toContain('The bridge was closed.')
  expect(wrapper.get('[data-testid="accept-candidate"]').attributes('disabled')).toBeDefined()
  await wrapper.get('input[aria-label="确认 warning 后接受"]').setValue(true)
  expect(wrapper.get('[data-testid="accept-candidate"]').attributes('disabled')).toBeUndefined()
})
```

- [ ] **Step 2: 确认测试失败**

Run: `npm test -- --run tests/teacher-ai-review-rendering.test.ts`

Expected: FAIL，因为组件不存在。

- [ ] **Step 3: 实现纯展示和受控表单组件**

`TeacherAiJobList.vue` 用语义化 `<button>` 渲染批次、状态、成功/失败数，当前项使用 `aria-current="true"`。`TeacherAiCandidateReview.vue` 使用 `reactive(structuredClone(props.draft.candidate))` 的可编辑副本；读取字段用 `readonly` 输入框；`rule_json` 通过 `JSON.stringify(..., null, 2)` 展示并在保存前解析。只在 `question_type === 'E4'` 渲染/提交 `reading_material`。

```vue
<button data-testid="accept-candidate" :disabled="!canAccept" type="button" @click="$emit('accept', { confirmWarnings: warningConfirmed })">接受并创建草稿</button>
<label v-if="validation?.status === 'warning'"><input v-model="warningConfirmed" aria-label="确认 warning 后接受" type="checkbox"> 我已阅读 warning</label>
<label>拒绝原因<select v-model="rejectReason" aria-label="拒绝原因"><option value="incorrect_answer">答案错误</option><option value="out_of_scope">超纲</option><option value="unclear_wording">表述不清</option><option value="duplicate">重复</option><option value="unsuitable_for_students">不适合学生</option><option value="other">其他</option></select></label>
```

- [ ] **Step 4: 确认 DOM 测试通过**

Run: `npm test -- --run tests/teacher-ai-review-rendering.test.ts`

Expected: PASS，覆盖 E4、证据、blocked/warning、拒绝 reason/detail、编辑事件和 accepted 提示。

- [ ] **Step 5: 提交**

```bash
git add apps/web/app/components/teacher/TeacherAiJobList.vue apps/web/app/components/teacher/TeacherAiCandidateReview.vue apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: render AI candidate review controls"
```

### Task 3: 组装独立路由、URL 恢复与错误恢复

**Files:**
- Create: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- Create: `apps/web/app/pages/teacher/ai-questions.vue`
- Modify: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes Tasks 1–2 的请求函数与事件。
- Produces `/teacher/ai-questions?job=<uuid>&draft=<uuid>` 的可恢复审核 UI。

- [ ] **Step 1: 写出失败的页面协调测试**

```ts
it('reloads the selected draft after a revision conflict instead of retaining stale edits', async () => {
  mocks.saveAiCandidateRevision.mockRejectedValue({ data: { detail: { code: 'review_revision_conflict' } } })
  const wrapper = await mountWorkspace({ query: { job: 'job-1', draft: 'draft-1' } })
  await wrapper.get('[data-testid="save-candidate"]').trigger('click')
  expect(mocks.fetchAiGenerationDrafts).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain('已加载最新修订')
})
```

- [ ] **Step 2: 确认测试失败**

Run: `npm test -- --run tests/teacher-ai-review-rendering.test.ts`

Expected: FAIL，因为工作区和路由不存在。

- [ ] **Step 3: 实现加载、会话和错误路径**

`TeacherAiReviewWorkspace.vue` 在 `onMounted` 和 `watch(() => route.query)` 中加载 jobs 和当前 job 的 drafts。通过 `fetchCurrentPrincipal($fetch)` 获得 CSRF token，写操作开始时锁定对应按钮、生成一次 `crypto.randomUUID()`，成功后重新读取 drafts。`navigateTo({ query: { job, draft } })` 是唯一选中状态同步方式。对 `review_revision_conflict` 执行 reload 并显示“候选已被更新，已加载最新修订。”；对 404、429、503 和网络错误显示公开中文提示且保留最后成功的页面数据。

`ai-questions.vue` 复用教师页面的侧栏、`TeacherWorkbenchNav active-module="ai_questions"`、顶部返回/退出控件，并将工作区放入 `main`。为页面标题设置“AI 出题审核”。

- [ ] **Step 4: 确认路由与组件测试通过**

Run: `npm test -- --run tests/teacher-ai-review.test.ts tests/teacher-ai-review-rendering.test.ts tests/teacher-workbench.test.ts`

Expected: PASS，覆盖深链恢复、冲突刷新、写入 loading、公开错误和窄屏结构 class。

- [ ] **Step 5: 提交**

```bash
git add apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/app/pages/teacher/ai-questions.vue apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: add teacher AI review workspace route"
```

### Task 4: 增加 E2E 种子与浏览器审核纵向切片

**Files:**
- Modify: `apps/api/src/edu_grader_api/e2e_support.py`
- Create: `apps/web/e2e/teacher-ai-review.spec.ts`
- Test: `apps/web/e2e/teacher-ai-review.spec.ts`

**Interfaces:**
- Consumes `/v1/ai-question-generation/jobs`, `/questions`, revision/reject/accept endpoints and the existing `e2e-teacher-token` session setup.
- Produces stable E2E job/draft fixture IDs discoverable by title/candidate prompt, without test-only bypass of auth or review checks.

- [ ] **Step 1: 写出失败的 Playwright 测试**

```ts
test('teacher edits, validates, rejects and accepts AI candidates through the browser', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions`)
  await page.getByRole('button', { name: /E2E AI review batch/ }).click()
  await page.getByLabel('答案规则 JSON').fill('{"expected":6}')
  await page.getByRole('button', { name: '保存并重新验证' }).click()
  await expect(page.getByText('验证已更新')).toBeVisible()
  await page.getByLabel('拒绝原因').selectOption('duplicate')
  await page.getByRole('button', { name: '拒绝候选题' }).click()
  await expect(page.getByText('已拒绝')).toBeVisible()
  await page.getByRole('button', { name: /候选题 2/ }).click()
  await page.getByRole('button', { name: '接受并创建草稿' }).click()
  await expect(page.getByText('已创建题库草稿')).toBeVisible()
})
```

- [ ] **Step 2: 确认 E2E 测试失败**

Run: `npm run test:e2e -- --grep "AI candidates"`

Expected: FAIL，因为 E2E 种子与页面尚未存在。

- [ ] **Step 3: 增加最小 E2E 种子与稳定选择器**

在 `seed_e2e_data` 的现有教师、课程目标和政策种子之后，用既有 `create_or_get_job` 与 `run_generation_job(..., FakeGenerationProvider(seed=0))` 建立一个两题 M1 批次；一个候选保持可通过，另一候选先由固定不合格规则产生可见 finding。只在不存在同一稳定 idempotency key 的 job 时创建，保证重复 E2E 启动幂等。Playwright 使用角色、标签和 `data-testid`，不依赖数据库 UUID。

- [ ] **Step 4: 确认浏览器链路通过**

Run: `npm run test:e2e -- --grep "AI candidates"`

Expected: PASS，证明浏览器通过真实认证与 API 走编辑→验证→拒绝→接受，接受结果仍为题库 draft。

- [ ] **Step 5: 提交**

```bash
git add apps/api/src/edu_grader_api/e2e_support.py apps/web/e2e/teacher-ai-review.spec.ts
git commit -m "test: cover teacher AI candidate review flow"
```

### Task 5: 全量验证和交付记录

**Files:**
- Modify: `docs/superpowers/plans/2026-07-22-teacher-ai-review-ui.md`

**Interfaces:**
- Consumes Tasks 1–4 的最终工作树。
- Produces可复现的 Web、构建、API 和浏览器验证记录。

- [ ] **Step 1: 运行目标 Vitest 套件**

Run: `npm test -- --run tests/teacher-ai-review.test.ts tests/teacher-ai-review-rendering.test.ts tests/teacher-workbench.test.ts`

Expected: PASS，0 failures。

- [ ] **Step 2: 运行完整 Web 质量门**

Run: `npm test && npm run build`

Expected: PASS，Vitest 无失败且 Nuxt production build 完成。

- [ ] **Step 3: 运行后端审核回归**

Run: `PYTHONPATH=apps/api/src;services/generator/src;packages/processor-policy/src python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py -q`

Expected: PASS，确认 UI 所消费的审核契约未被破坏。

- [ ] **Step 4: 记录验证并检查 diff**

Add a dated `## Delivery verification` section with each command and actual result. Then run:

```bash
git diff --check origin/main...HEAD
git status --short
```

Expected: diff check 无输出；除该计划记录外无意外文件。

- [ ] **Step 5: 提交**

```bash
git add docs/superpowers/plans/2026-07-22-teacher-ai-review-ui.md
git commit -m "docs: record AI review workspace verification"
```

## Plan Self-Review

- **Spec coverage:** Task 1 覆盖受限 API/幂等与导航；Task 2 覆盖候选字段、E4、证据与审核门禁；Task 3 覆盖深链、刷新、错误和响应式布局；Task 4 覆盖真实浏览器垂直切片；Task 5 覆盖质量门与交付记录。
- **Placeholder scan:** 本计划没有未定义动作或待补充步骤；每个任务列出路径、接口、失败测试、实现边界、命令和提交。
- **Type consistency:** 所有组件都消费 Task 1 的 `TeacherAi*` 投影；所有写事件统一使用 `expected_revision_number`、CSRF 和 `Idempotency-Key`。

## Delivery verification — 2026-07-22

- `cd apps/web && npm test -- --run tests/teacher-ai-review.test.ts tests/teacher-ai-review-rendering.test.ts tests/teacher-workbench.test.ts`: PASS（exit 0）；3 个测试文件、41 个测试全部通过。
- `cd apps/web && npm test && npm run build`: PASS（exit 0）；Vitest 16 个测试文件、83 个测试全部通过，Nuxt 4.4.8 client、SSR 和 Nitro production build 完成。构建继续报告 module-preload sourcemap、超过 500 kB chunk 和 Node trailing-slash exports deprecation 警告。
- PowerShell 等价执行：`$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src'; python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py -q`: PASS（exit 0）；37 个测试全部通过。
- `cd apps/web && npm run test:e2e -- --grep "AI candidates"`: PASS（exit 0）；E2E runtime supervisor 3/3 通过，Chromium 中教师编辑、同步重验、拒绝并接受 AI 候选的真实浏览器垂直切片 1/1 通过。
- `git diff --check origin/main...HEAD`: PASS（exit 0），无输出；首次检查发现 `docs/superpowers/specs/2026-07-22-teacher-ai-review-ui-design.md` EOF 多余空行，删除该精确空行并 amend 后复检通过。
- `git status --short`: 验证记录提交前仅本计划文件被修改，另有按要求未暂存、未提交的 `.superpowers/` 报告目录；为使范围 diff clean，随后仅额外修正并提交上述设计文档 EOF 空行，未发现其他意外文件。
