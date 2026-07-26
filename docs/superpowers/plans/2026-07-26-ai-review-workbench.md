# AI 出题审核工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把教师端 AI 出题审核重构为清晰、响应式的三栏决策工作台，同时保持全部现有审核状态机和 API 行为。

**Architecture:** `TeacherAiReviewWorkspace` 继续持有批次选择、路由同步和 API 写入状态，只重新排列候选列表、候选预览、审核结论和折叠的批量工具。`TeacherAiCandidateReview` 保留编辑草稿、warning 确认和拒绝详情的本地输入状态。新的展示组件只消费 draft 与 validation，不发起请求，也不复制 `canAcceptCandidate` 的门禁逻辑。

**Tech Stack:** Nuxt 4、Vue 3、Vitest、Vue Test Utils、Playwright、现有全局 CSS。

## Global Constraints

- 保留 `/teacher/ai-questions?job=<id>&draft=<id>` 深链接和刷新恢复。
- 不改变 `passed`、`warning`、`blocked`、`accepted`、`rejected` 的业务意义或 API 调用。
- 只有 `canAcceptCandidate` 可以决定接受按钮是否可用；warning 仍需显式确认，blocked 仍不得接受。
- 接受动作继续只创建题库草稿，不直接发布给学生。
- 不新增后端 API、数据库迁移、搜索或筛选。
- 320px 宽度下无横向溢出，所有触控操作最小高度 44px。

---

### Task 1: 定义失败的审核工作台契约

**Files:**
- Modify: `apps/web/tests/teacher-ai-review-rendering.test.ts`
- Modify: `apps/web/e2e/teacher-ai-review.spec.ts`

**Interfaces:**
- Consumes: 当前 `TeacherAiReviewWorkspace`、`TeacherAiCandidateReview`、warning/blocked fixtures。
- Produces: 语义区域、中文结论、技术信息折叠和移动端布局的回归契约。

- [ ] **Step 1: 为三栏区域和 warning 结论写失败测试**

在 `teacher-ai-review-rendering.test.ts` 的 suite 中添加：

```ts
it('renders a decision-focused workbench with a readable warning conclusion', async () => {
  const wrapper = await mountWorkspace()

  expect(wrapper.get('[data-testid="ai-review-candidate-list"]')).toBeTruthy()
  expect(wrapper.get('[data-testid="ai-review-preview"]')).toBeTruthy()
  expect(wrapper.get('[data-testid="ai-review-decision"]')).toBeTruthy()
  expect(wrapper.get('[data-testid="review-decision-heading"]').text()).toBe('可接受，但请先确认提醒')
  expect(wrapper.get('[data-testid="review-decision-next-step"]').text()).toContain('勾选“我已阅读提醒”')
  expect(wrapper.get('[data-testid="advanced-review-information"]').attributes('open')).toBeUndefined()
})
```

- [ ] **Step 2: 运行渲染测试，确认它因缺少新区域失败**

Run: `npm test -- teacher-ai-review-rendering.test.ts`

Expected: FAIL because the new `data-testid` attributes and readable decision copy do not exist.

- [ ] **Step 3: 为阻断和终态写失败测试**

```ts
it('explains blocked candidates without offering acceptance', () => {
  const wrapper = mount(TeacherAiCandidateReview, {
    props: { draft: warningE4Draft, validation: blockedValidation },
  })

  expect(wrapper.get('[data-testid="review-decision-heading"]').text()).toBe('暂不能接受')
  expect(wrapper.get('[data-testid="review-decision-next-step"]').text()).toContain('修改题目、重新生成或拒绝')
  expect(wrapper.get('[data-testid="accept-candidate"]').attributes('disabled')).toBeDefined()
})

it('explains accepted candidates as question-bank drafts', () => {
  const wrapper = mount(TeacherAiCandidateReview, {
    props: {
      draft: { ...warningE4Draft, teacher_state: 'accepted' },
      validation: warningValidation,
      acceptedQuestionVersionId: 'version-1',
    },
  })

  expect(wrapper.get('[data-testid="accepted-notice"]').text()).toContain('尚未发布给学生')
})
```

- [ ] **Step 4: 为 320px E2E 写失败断言**

在 `teacher-ai-review.spec.ts` 增加：

```ts
test('AI review workbench remains readable and without horizontal overflow at 320px', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 320, height: 720 } })
  const page = await context.newPage()
  try {
    await signInAsTeacher(page)
    await page.goto('/teacher/ai-questions')
    await expect(page.getByTestId('ai-review-candidate-list')).toBeVisible()
    await expect(page.getByTestId('ai-review-decision')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  } finally {
    await context.close()
  }
})
```

- [ ] **Step 5: 运行 E2E，确认它因缺少新工作台失败**

Run: `NUXT_IGNORE_LOCK=1 npx playwright test e2e/teacher-ai-review.spec.ts --project=chromium --grep '320px'`

Expected: FAIL because the workbench test IDs do not exist.

- [ ] **Step 6: Commit the red contract**

```bash
git add apps/web/tests/teacher-ai-review-rendering.test.ts apps/web/e2e/teacher-ai-review.spec.ts
git commit -m "test: define AI review workbench contract"
```

### Task 2: 实现可读的审核结论与候选预览

**Files:**
- Create: `apps/web/app/components/teacher/TeacherAiReviewDecision.vue`
- Modify: `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- Modify: `apps/web/app/assets/css/main.css`
- Modify: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes: `TeacherAiDraft`, `TeacherAiValidationRun | null` 和当前 candidate-review emits。
- Produces: `TeacherAiReviewDecision` with props `draft`, `validation`, `warningConfirmed`, `acceptedQuestionVersionId`; 现有 save/reject/accept/regenerate emits 不变。

- [ ] **Step 1: 创建纯展示的审核结论组件**

在 `TeacherAiReviewDecision.vue` 中按状态计算文案：

```ts
const state = computed(() => {
  if (props.draft.teacher_state === 'accepted') return {
    heading: '已创建题库草稿', nextStep: '请前往题库测试并发布；学生尚未看到这道题。',
  }
  if (props.draft.teacher_state === 'rejected') return {
    heading: '已拒绝', nextStep: '该候选保留审核记录，不能再修改或接受。',
  }
  if (!props.validation || props.validation.status === 'blocked') return {
    heading: '暂不能接受', nextStep: '请修改题目、重新生成或拒绝；阻断问题解决前不能创建草稿。',
  }
  if (props.validation.status === 'warning') return {
    heading: '可接受，但请先确认提醒', nextStep: '阅读每条提醒后，勾选“我已阅读提醒”才能接受。',
  }
  return { heading: '可以接受', nextStep: '接受后会创建题库草稿，仍需测试和发布。' }
})
```

渲染 `ai-review-decision`、`review-decision-heading`、`review-decision-next-step` test IDs；对每条 finding 显示 remediation。不得在该组件执行写请求或重新实现接受门禁。

- [ ] **Step 2: 将候选组件重组为预览、参考、编辑和高级信息**

保留现有 reactive candidate、JSON 解析、warning checkbox、拒绝详情和 emits。改用如下结构：

```vue
<section class="ai-candidate-review" aria-label="AI 候选题审核">
  <section data-testid="ai-review-preview" class="ai-candidate-review__preview">…学生可见题干与 E4 阅读材料…</section>
  <section class="ai-candidate-review__reference" aria-label="教师参考">…解析、知识点、难度…</section>
  <details data-testid="candidate-editor"><summary>编辑题目</summary>…现有编辑控件与保存按钮…</details>
  <details data-testid="advanced-review-information"><summary>高级信息</summary>…目标修订、策略版本、评分规则 JSON…</details>
  <TeacherAiReviewDecision … />
  …保留 warning 确认、接受、拒绝和终态通知…
</section>
```

接受按钮文字改为“接受为题库草稿”；已接受通知补充“尚未发布给学生”。

- [ ] **Step 3: 添加仅限 AI 审核页的样式**

在 `main.css` 增加 `.ai-candidate-review` 和 `.ai-review-decision` 前缀规则：卡片区用 grid/gap，`details summary` 最小高度 44px，表单标签在组件内用列布局，所有输入宽度 100%。禁止对全局裸 `label`、`input`、`textarea`、`button` 写规则。

- [ ] **Step 4: 运行 Task 1 的单元测试，确认转绿**

Run: `npm test -- teacher-ai-review-rendering.test.ts`

Expected: PASS, including existing warning confirmation、blocked prevention and terminal read-only tests.

- [ ] **Step 5: Commit the preview and decision redesign**

```bash
git add apps/web/app/components/teacher/TeacherAiReviewDecision.vue apps/web/app/components/teacher/TeacherAiCandidateReview.vue apps/web/app/assets/css/main.css apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: clarify AI candidate review decisions"
```

### Task 3: 装配响应式三栏工作台与折叠批量工具

**Files:**
- Modify: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- Modify: `apps/web/app/assets/css/main.css`
- Modify: `apps/web/tests/teacher-ai-review-rendering.test.ts`
- Modify: `apps/web/e2e/teacher-ai-review.spec.ts`

**Interfaces:**
- Consumes: `TeacherAiCandidateReview` 的既有 emits、`batchSelectionReady`、`batchItems` 与 `currentBatchSelectable`。
- Produces: 宽屏三栏、窄屏单列的工作台，不改变 route query 和现有 API 请求。

- [ ] **Step 1: 将 workspace 改为语义三栏**

保留 `TeacherAiJobList`、候选选择按钮、批量计算属性和写入 handlers。为现有区域添加稳定边界：

```vue
<div class="ai-review-workspace__grid">
  <aside data-testid="ai-review-candidate-list" class="ai-review-workspace__candidates" aria-label="候选题列表">…</aside>
  <main class="ai-review-workspace__content" aria-live="polite"><TeacherAiCandidateReview … /></main>
  <aside class="ai-review-workspace__decision-rail" aria-label="审核操作说明">…</aside>
</div>
```

将“加入批量接受”和“批量接受并创建草稿”移动到 `<details data-testid="batch-review-tools" class="ai-review-workspace__batch-tools">`，summary 使用“批量处理（已选 {{ selectedBatchDraftIds.length }} 题）”。单题审核动作仍在候选组件中。

- [ ] **Step 2: 实现移动优先的响应式 CSS**

```css
.ai-review-workspace__grid { display: grid; gap: 20px; }
.ai-review-workspace__candidates, .ai-review-workspace__content, .ai-review-workspace__decision-rail { min-width: 0; }
@media (min-width: 980px) {
  .ai-review-workspace__grid { grid-template-columns: minmax(210px, .24fr) minmax(0, 1fr) minmax(230px, .3fr); align-items: start; }
  .ai-review-workspace__decision-rail { position: sticky; top: 20px; }
}
@media (max-width: 759px) {
  .ai-review-workspace__candidates button, .ai-candidate-review .button { min-height: 44px; width: 100%; }
}
```

不要使用固定宽度、`100vw`、全局选择器或隐藏审核信息。

- [ ] **Step 3: 覆盖折叠批量工具的渲染状态**

```ts
it('keeps batch acceptance available but out of the single-candidate decision path', async () => {
  const wrapper = await mountWorkspace()
  const tools = wrapper.get('[data-testid="batch-review-tools"]')

  expect(tools.element).toBeInstanceOf(HTMLDetailsElement)
  expect(tools.attributes('open')).toBeUndefined()
  expect(wrapper.get('[data-testid="accept-candidate"]').text()).toBe('接受为题库草稿')
})
```

- [ ] **Step 4: 运行审核单测和桌面/移动 E2E**

Run: `npm test -- teacher-ai-review-rendering.test.ts`

Expected: PASS.

Run: `NUXT_IGNORE_LOCK=1 npx playwright test e2e/teacher-ai-review.spec.ts --project=chromium`

Expected: PASS, including existing review flow and the 320px overflow assertion.

- [ ] **Step 5: Commit the responsive workbench**

```bash
git add apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/app/assets/css/main.css apps/web/tests/teacher-ai-review-rendering.test.ts apps/web/e2e/teacher-ai-review.spec.ts
git commit -m "feat: build responsive AI review workbench"
```

### Task 4: 完整验证

**Files:**
- Verify only: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- Verify only: `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- Verify only: `apps/web/app/components/teacher/TeacherAiReviewDecision.vue`

**Interfaces:**
- Consumes: 完成后的工作台与 Nuxt 构建配置。
- Produces: 发布前验证证据；不引入额外功能。

- [ ] **Step 1: 运行完整前端单测**

Run: `npm test`

Expected: all tests pass with 0 failures.

- [ ] **Step 2: 运行生产构建**

Run: `npm run build`

Expected: exit code 0; existing chunk-size and sourcemap warnings may remain but no build error.

- [ ] **Step 3: 检查空白和变更范围**

Run: `git diff --check && git status --short`

Expected: AI review files are the only new changes; preserve the pre-existing `.gitignore` modification.

- [ ] **Step 4: Commit the verification-ready implementation**

```bash
git add apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/app/components/teacher/TeacherAiCandidateReview.vue apps/web/app/components/teacher/TeacherAiReviewDecision.vue apps/web/app/assets/css/main.css apps/web/tests/teacher-ai-review-rendering.test.ts apps/web/e2e/teacher-ai-review.spec.ts
git commit -m "test: verify AI review workbench"
```
