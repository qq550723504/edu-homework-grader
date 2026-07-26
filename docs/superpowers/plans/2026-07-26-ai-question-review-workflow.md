# AI Question Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/teacher/ai-questions` explain the generated-question lifecycle and present only the valid next review action for each candidate state.

**Architecture:** Add a small pure presentation mapper that converts the existing server-owned draft and validation state into teacher-facing labels, explanations, and action guidance. Keep all API requests, state transitions, CSRF, idempotency, route selection, and acceptance eligibility in the existing review workspace; restructure Vue templates around that mapper and introduce no backend contract or database change.

**Tech Stack:** Nuxt 4, Vue 3 Composition API, TypeScript, Vitest + Vue Test Utils, Playwright.

## Global Constraints

- Do not modify generation, validation, review, question-bank, assignment, or student-facing API contracts.
- AI output remains a candidate; acceptance creates a `QuestionVersion` draft only and never publishes a question to students.
- The server remains authoritative for validation and acceptance; a `blocked` candidate is never selectable or acceptable.
- A `warning` candidate requires explicit per-candidate acknowledgement before single or batch acceptance.
- Preserve CSRF, Idempotency-Key, atomic bulk acceptance, route query selection, existing error mapping, and all existing `data-testid` values used by E2E tests.
- Do not expose provider credentials, system prompts, private validator features, or unsanitized server internals.

---

## File Structure

- Create `apps/web/app/lib/teacher-ai-review-presentation.ts`: pure mapping from `TeacherAiDraft` plus its current validation run to the status language and recommended action shown in the UI.
- Create `apps/web/tests/teacher-ai-review-presentation.test.ts`: direct unit tests for every teacher-facing state, independent of Vue rendering.
- Modify `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`: render the student preview, decision summary, contextual actions, editable fields, and technical evidence in the agreed priority order.
- Modify `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`: render the lifecycle progress strip, populate per-draft validation summaries, show comprehensible candidate status labels, and reposition/reword the existing bulk selection controls.
- Modify `apps/web/tests/teacher-ai-review-rendering.test.ts`: retain write-flow regression coverage and add rendering/selection assertions for the new information hierarchy.
- Modify `apps/web/e2e/teacher-ai-review.spec.ts`: assert the visible lifecycle and non-publication language while retaining the current generated-to-draft acceptance integration path.

### Task 1: Add the pure teacher-facing review presentation model

**Files:**
- Create: `apps/web/app/lib/teacher-ai-review-presentation.ts`
- Test: `apps/web/tests/teacher-ai-review-presentation.test.ts`

**Interfaces:**
- Consumes: `TeacherAiDraft` and `TeacherAiValidationRun | null` from `apps/web/app/lib/teacher-ai-review.ts`.
- Produces: `reviewPresentation(draft, validation): TeacherAiReviewPresentation`, used by both review Vue components.

- [ ] **Step 1: Write the failing state-mapping tests**

```ts
import { describe, expect, it } from 'vitest'
import { reviewPresentation } from '../app/lib/teacher-ai-review-presentation'

it('explains a blocked pending candidate as requiring correction', () => {
  expect(reviewPresentation(pendingDraft, blockedRun)).toMatchObject({
    kind: 'needs_fix', label: '需修正', title: '暂不能接受',
    primaryAction: '修改并重新校验',
  })
})

it.each([
  ['warning', 'needs_confirmation', '需要教师确认', '已阅读后接受为题库草稿'],
  ['passed', 'ready', '可以接受', '接受为题库草稿'],
])('maps %s validations to a teacher decision', (status, kind, title, primaryAction) => {
  expect(reviewPresentation(pendingDraft, { ...passedRun, status })).toMatchObject({ kind, title, primaryAction })
})

it.each([
  ['accepted', 'accepted', '已创建题库草稿'],
  ['rejected', 'rejected', '已拒绝这道候选题'],
])('maps terminal teacher state %s without an available write action', (teacher_state, kind, title) => {
  expect(reviewPresentation({ ...pendingDraft, teacher_state }, passedRun)).toMatchObject({ kind, title, primaryAction: null })
})
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `npm test -- tests/teacher-ai-review-presentation.test.ts` from `apps/web`.

Expected: FAIL because `teacher-ai-review-presentation.ts` does not exist.

- [ ] **Step 3: Implement the presentation model**

```ts
import type { TeacherAiDraft, TeacherAiValidationRun } from './teacher-ai-review'

export type TeacherAiReviewPresentationKind =
  | 'needs_fix' | 'needs_confirmation' | 'ready' | 'accepted' | 'rejected' | 'waiting'

export interface TeacherAiReviewPresentation {
  kind: TeacherAiReviewPresentationKind
  label: string
  title: string
  description: string
  primaryAction: string | null
}

export function reviewPresentation(
  draft: TeacherAiDraft,
  validation: TeacherAiValidationRun | null,
): TeacherAiReviewPresentation {
  if (draft.teacher_state === 'accepted') return {
    kind: 'accepted', label: '已接受', title: '已创建题库草稿',
    description: '题目尚未发布给学生；请在题库中组卷后再发布作业。', primaryAction: null,
  }
  if (draft.teacher_state === 'rejected') return {
    kind: 'rejected', label: '已拒绝', title: '已拒绝这道候选题',
    description: '该候选题不会进入题库。', primaryAction: null,
  }
  if (!validation) return {
    kind: 'waiting', label: '待校验', title: '正在等待系统校验',
    description: '校验结果返回前不能接受这道题。', primaryAction: null,
  }
  if (validation.status === 'blocked') return {
    kind: 'needs_fix', label: '需修正', title: '暂不能接受',
    description: validation.findings[0]?.remediation ?? '请修正题目后重新校验，或重新生成、拒绝这道题。',
    primaryAction: '修改并重新校验',
  }
  if (validation.status === 'warning') return {
    kind: 'needs_confirmation', label: '需确认', title: '需要教师确认',
    description: validation.findings[0]?.remediation ?? '请阅读系统提醒后决定是否接受。',
    primaryAction: '已阅读后接受为题库草稿',
  }
  return {
    kind: 'ready', label: '可以接受', title: '可以接受',
    description: '已通过系统校验；接受后只会创建题库草稿。', primaryAction: '接受为题库草稿',
  }
}
```

- [ ] **Step 4: Run the presentation tests to verify they pass**

Run: `npm test -- tests/teacher-ai-review-presentation.test.ts` from `apps/web`.

Expected: PASS; each `blocked`, `warning`, `passed`, `accepted`, and `rejected` case has stable copy.

- [ ] **Step 5: Commit the isolated presentation model**

```bash
git add apps/web/app/lib/teacher-ai-review-presentation.ts apps/web/tests/teacher-ai-review-presentation.test.ts
git commit -m "feat: describe AI review states for teachers"
```

### Task 2: Reorder the single-candidate review around the decision

**Files:**
- Modify: `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- Test: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes: `reviewPresentation(draft, validation)`, existing `canAcceptCandidate`, existing emits (`save-revision`, `accept`, `reject`, `regenerate`).
- Produces: stable test IDs `review-student-preview`, `review-decision`, `edit-candidate-details`, and `technical-review-details`; preserves existing input labels and action test IDs.

- [ ] **Step 1: Write failing component tests for the reordered workflow**

```ts
it('shows the student preview, blocked reason, and corrective action before editable internals', () => {
  const wrapper = mount(TeacherAiCandidateReview, {
    props: { draft: warningE4Draft, validation: { ...warningValidation, status: 'blocked' } },
  })
  expect(wrapper.get('[data-testid="review-student-preview"]').text()).toContain('Why was the bridge closed?')
  expect(wrapper.get('[data-testid="review-decision"]').text()).toContain('暂不能接受')
  expect(wrapper.get('[data-testid="review-decision"]').text()).toContain('Resolve this validation finding')
  expect(wrapper.get('[data-testid="edit-candidate-details"]').exists()).toBe(true)
  expect(wrapper.get('[data-testid="technical-review-details"]').exists()).toBe(true)
})

it('explains that acceptance creates a draft rather than publishing to students', () => {
  const wrapper = mount(TeacherAiCandidateReview, { props: { draft: warningE4Draft, validation: passedValidation } })
  expect(wrapper.get('[data-testid="review-decision"]').text()).toContain('只会创建题库草稿')
  expect(wrapper.get('[data-testid="accept-candidate"]').text()).toBe('接受为题库草稿')
})
```

- [ ] **Step 2: Run the rendering test to verify it fails**

Run: `npm test -- tests/teacher-ai-review-rendering.test.ts` from `apps/web`.

Expected: FAIL because the new decision and disclosure test IDs do not exist.

- [ ] **Step 3: Restructure `TeacherAiCandidateReview.vue` without changing its write contracts**

```vue
<section aria-label="AI 候选题审核">
  <section data-testid="review-student-preview" aria-labelledby="student-preview-heading">
    <p class="eyebrow">当前候选题 · 第 {{ draft.ordinal }} 题</p>
    <h2 id="student-preview-heading">学生将看到的题目</h2>
    <p>{{ candidate.prompt }}</p>
    <p v-if="candidate.question_type === 'E4'">{{ candidate.reading_material }}</p>
    <p>知识点：{{ candidate.knowledge_point }} · 目标难度：{{ candidate.difficulty }}</p>
  </section>

  <section data-testid="review-decision" aria-live="polite">
    <h2>系统审核结果</h2>
    <h3>{{ presentation.title }}</h3>
    <p>{{ presentation.description }}</p>
    <label v-if="presentation.kind === 'needs_confirmation'">
      <input v-model="warningConfirmed" :disabled="writeDisabled" aria-label="确认 warning 后接受" type="checkbox">
      我已阅读此提醒
    </label>
    <button v-if="presentation.kind === 'ready' || presentation.kind === 'needs_confirmation'"
      :disabled="writeDisabled || !canAccept" data-testid="accept-candidate" type="button" @click="acceptCandidate">
      接受为题库草稿
    </button>
  </section>

  <details v-if="!accepted && draft.teacher_state === 'pending_review'" data-testid="edit-candidate-details">
    <summary>修改题目</summary>
    <!-- Preserve the existing 题目提示、评分规则 JSON、解析、知识点、难度、阅读材料 fields and 保存修订 test ID. -->
  </details>
  <details data-testid="technical-review-details">
    <summary>高级信息：评分规则与技术记录</summary>
    <!-- Preserve finding code, remediation, evidence and formatted rule JSON here. -->
  </details>
</section>
```

Keep `saveRevision`, `rejectCandidate`, `acceptCandidate`, `regenerateCandidate`, `candidateEditInput`, and their emit payloads unchanged. Add `const presentation = computed(() => reviewPresentation(props.draft, props.validation))`; do not infer acceptance from `presentation` instead of `canAcceptCandidate`.

- [ ] **Step 4: Run focused component rendering tests**

Run: `npm test -- tests/teacher-ai-review-rendering.test.ts` from `apps/web`.

Expected: PASS; existing editing, validation, warning confirmation, rejection detail, accepted/rejected read-only, and regeneration tests continue to pass alongside the new hierarchy assertions.

- [ ] **Step 5: Commit the candidate review redesign**

```bash
git add apps/web/app/components/teacher/TeacherAiCandidateReview.vue apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: guide teachers through AI candidate review"
```

### Task 3: Add workspace lifecycle context and authoritative batch status summaries

**Files:**
- Modify: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- Modify: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes: `reviewPresentation`, `fetchAiValidationRuns`, existing `TeacherAiCandidateReview` events and current batch selection state.
- Produces: `data-testid="ai-review-lifecycle"`, per-draft `data-testid="draft-status-<draft-id>"`, and retained batch action test IDs.

- [ ] **Step 1: Write failing workspace tests**

```ts
it('shows the lifecycle and a teacher-facing status for every draft in the selected batch', async () => {
  const secondDraft = { ...warningE4Draft, id: 'draft-2', ordinal: 2, teacher_state: 'accepted' }
  mocks.fetchAiGenerationDrafts.mockResolvedValue([warningE4Draft, secondDraft])
  mocks.fetchAiValidationRuns.mockImplementation((_request, draftId) => Promise.resolve([
    draftId === 'draft-1' ? warningValidation : { ...warningValidation, draft_id: draftId, status: 'passed' },
  ]))
  const wrapper = await mountWorkspace()
  expect(wrapper.get('[data-testid="ai-review-lifecycle"]').text()).toContain('教师审核')
  expect(wrapper.get('[data-testid="draft-status-draft-1"]').text()).toContain('需确认')
  expect(wrapper.get('[data-testid="draft-status-draft-2"]').text()).toContain('已接受')
})

it('uses the count in the bulk acceptance action without selecting blocked drafts', async () => {
  const wrapper = await mountWorkspace()
  await wrapper.get('[data-testid="batch-select-draft-1"]').setValue(true)
  await wrapper.get('[data-testid="batch-warning-draft-1"]').setValue(true)
  expect(wrapper.get('[data-testid="bulk-accept-candidates"]').text()).toContain('接受已选 1 题为题库草稿')
})
```

- [ ] **Step 2: Run the workspace rendering test to verify it fails**

Run: `npm test -- tests/teacher-ai-review-rendering.test.ts` from `apps/web`.

Expected: FAIL because lifecycle and status test IDs are absent and the old batch label has no count.

- [ ] **Step 3: Fetch current validation summaries for each selected-job draft and render the workbench context**

```ts
const validationByDraftId = ref<Record<string, TeacherAiValidationRun | null>>({})
const selectedValidation = computed(() => {
  const draft = selectedDraft.value
  return draft ? validationByDraftId.value[draft.id] ?? null : null
})

async function fetchValidationSummaries(drafts: TeacherAiDraft[]) {
  const entries = await Promise.all(drafts.map(async (draft) => [
    draft.id,
    await fetchCurrentValidation(draft),
  ] as const))
  return Object.fromEntries(entries)
}
```

In `loadWorkspace`, fetch summaries after fetching selected-job drafts and assign them only after `requestIsCurrent(...)` succeeds. In `refreshSelection`, refresh the affected draft entry after its write result. Clear this map whenever the route switches jobs. Do not replace the current validation key/version guard used by pending-write refresh logic.

Replace the current plain candidate list label with `reviewPresentation(draft, validationByDraftId[draft.id]).label`, preserving each `generation-draft-*` button. Insert this read-only lifecycle block above the workspace grid:

```vue
<nav data-testid="ai-review-lifecycle" aria-label="AI 出题流程">
  <span>1 生成批次</span><span>2 系统校验</span><strong>3 教师审核</strong>
  <span>4 题库草稿</span><span>5 组卷并发布</span>
</nav>
```

Keep the current checkbox and warning acknowledgement state machines. Move their visible toolbar below the candidate review, label it `批量接受`, and change the existing button copy to `接受已选 {{ selectedBatchDraftIds.length }} 题为题库草稿`; keep `data-testid="bulk-accept-candidates"` unchanged.

- [ ] **Step 4: Run workspace and API-client regression tests**

Run: `npm test -- tests/teacher-ai-review-rendering.test.ts tests/teacher-ai-review.test.ts` from `apps/web`.

Expected: PASS; per-draft summaries render from fetched validation runs, blocked drafts remain disabled, warnings remain individually acknowledged, and existing idempotent batch behavior is unchanged.

- [ ] **Step 5: Commit the workspace information architecture**

```bash
git add apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "feat: clarify AI review batch progress"
```

### Task 4: Verify the end-to-end teacher language and full Web build

**Files:**
- Modify: `apps/web/e2e/teacher-ai-review.spec.ts`

**Interfaces:**
- Consumes: stable lifecycle, decision, and bulk-action test IDs from Tasks 2–3.
- Produces: coverage that the visible UI explains the candidate-to-draft boundary without altering the accepted API results.

- [ ] **Step 1: Write failing E2E assertions at the existing G7 review entry point**

```ts
await expect(page.getByTestId('ai-review-lifecycle')).toContainText('教师审核')
await expect(page.getByTestId('review-decision')).toContainText('暂不能接受')
await expect(page.getByTestId('review-decision')).toContainText('修改并重新校验')
```

After the existing atomic acceptance response, add:

```ts
await expect(page.getByTestId('accepted-notice')).toContainText('已创建题库草稿')
await expect(page.getByTestId('accepted-notice')).not.toContainText('学生已看到')
```

- [ ] **Step 2: Run the focused browser test to verify it fails**

Run: `npx playwright test e2e/teacher-ai-review.spec.ts` from `apps/web` with the repository E2E services running.

Expected: FAIL before Tasks 2–3 are complete because the lifecycle and decision test IDs are absent.

- [ ] **Step 3: Run the focused browser test after implementation**

Run: `npx playwright test e2e/teacher-ai-review.spec.ts` from `apps/web` with the repository E2E services running.

Expected: PASS; the blocked M1 remains server-rejected until repaired, accepted M1/M2 records are `draft`, and the UI explains that they are not yet student-visible.

- [ ] **Step 4: Run the Web regression suite and production build**

Run: `npm test -- tests/teacher-ai-review-presentation.test.ts tests/teacher-ai-review-rendering.test.ts tests/teacher-ai-review.test.ts` from `apps/web`.

Expected: PASS.

Run: `npm run build` from `apps/web`.

Expected: PASS with Nuxt production output generated and no TypeScript/template error.

- [ ] **Step 5: Commit verification coverage**

```bash
git add apps/web/e2e/teacher-ai-review.spec.ts
git commit -m "test: cover AI review workflow guidance"
```

## Plan Self-Review

- **Spec coverage:** Task 1 maps all teacher-visible states; Task 2 enforces the student-preview → decision → action hierarchy and keeps technical data secondary; Task 3 adds lifecycle context, batch state labels and safe bulk wording; Task 4 verifies the candidate-to-draft boundary in a real browser and completes the focused regression/build gate.
- **Completeness scan:** every task names files, interfaces, concrete tests, commands, expected outcomes, and a scoped commit.
- **Type consistency:** every component consumes `TeacherAiDraft`, `TeacherAiValidationRun | null`, and `reviewPresentation`; all writes retain existing event signatures and existing API-client types.
