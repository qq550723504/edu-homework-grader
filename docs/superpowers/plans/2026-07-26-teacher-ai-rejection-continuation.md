# Teacher AI Rejection Continuation Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let teachers continue after rejecting an AI candidate without changing the rejected candidate's immutable audit state.

**Architecture:** `TeacherAiCandidateReview` renders state-specific continuation actions and emits user intent. `TeacherAiReviewWorkspace` owns batch ordering, route-only next-candidate navigation, and reuses the existing regeneration API client for pending and rejected source drafts. The API and persistence state machine do not change.

**Tech Stack:** Nuxt 4, Vue 3 `<script setup>`, TypeScript, Vitest, Vue Test Utils, Playwright.

## Global Constraints

- A rejected source draft remains rejected and never receives edit, accept, batch-accept, or reject controls.
- Reuse `regenerateAiCandidate`; do not add a rejection-specific API route or server transition.
- A regenerated candidate is a distinct one-item job and preserves the source draft audit record.
- Move to another candidate only after an explicit teacher action.
- Keep accepted-candidate question-bank continuation unchanged.

---

### Task 1: Add rejected-state continuation actions and workspace routing

**Files:**
- Modify: `apps/web/app/components/teacher/TeacherAiCandidateReview.vue`
- Modify: `apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue`
- Test: `apps/web/tests/teacher-ai-review-rendering.test.ts`

**Interfaces:**
- Consumes: `TeacherAiDraft.teacher_state`, `regenerateAiCandidate(request, csrfToken, draftId, key)`, and the workspace `drafts` ordering.
- Produces: candidate events `regenerate` and `continue-review`; test ids `regenerate-candidate`, `continue-review-next-candidate`, and `generate-new-ai-batch`.

- [ ] **Step 1: Write failing component tests**

Add rejected-state coverage next to the terminal-state tests:

```ts
it('offers a rejected candidate regeneration while keeping it immutable', () => {
  const wrapper = mount(TeacherAiCandidateReview, {
    props: { draft: { ...warningE4Draft, teacher_state: 'rejected' }, validation: warningValidation },
  })

  expect(wrapper.get('[data-testid="rejected-notice"]').text()).toContain('已拒绝')
  expect(wrapper.get('[data-testid="regenerate-candidate"]').text()).toContain('重新生成同题型候选题')
  expect(wrapper.find('[data-testid="save-revision"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="accept-candidate"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="reject-candidate"]').exists()).toBe(false)
})
```

Add a second test with `hasNextReviewCandidate: true`; click `continue-review-next-candidate` and expect `wrapper.emitted('continue-review')`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
npm test -- --run tests/teacher-ai-review-rendering.test.ts
```

Expected: FAIL because the rejected candidate has no regeneration action or continuation event.

- [ ] **Step 3: Write failing workspace tests**

Add one test for regeneration from a rejected source:

```ts
it('regenerates a rejected source draft and preserves its audit state', async () => {
  mocks.fetchAiGenerationDrafts.mockResolvedValue([
    { ...warningE4Draft, teacher_state: 'rejected' },
  ])
  const wrapper = await mountWorkspace()

  await wrapper.get('[data-testid="regenerate-candidate"]').trigger('click')
  await flushPromises()

  expect(mocks.regenerateAiCandidate).toHaveBeenCalledWith(
    expect.any(Function), 'csrf-token', 'draft-1', 'operation-key',
  )
  expect(navigateTo).toHaveBeenCalledWith({ query: { job: 'job-regenerated' } })
})
```

Add a second test with rejected `draft-1` and pending `draft-2`; click `continue-review-next-candidate` and expect `navigateTo({ query: { job: 'job-1', draft: 'draft-2' } })`. Add a one-item rejected batch expectation for `generate-new-ai-batch` with `href="/teacher/ai-questions/new"`.

- [ ] **Step 4: Verify RED**

Run:

```powershell
npm test -- --run tests/teacher-ai-review-rendering.test.ts
```

Expected: FAIL because `regenerateCandidate()` returns early for a rejected draft and no next-candidate action or new-batch link exists.

- [ ] **Step 5: Implement the minimal UI flow**

In `TeacherAiCandidateReview.vue`, add:

```ts
const rejected = computed(() => props.draft.teacher_state === 'rejected')
const canRegenerate = computed(() => pendingReview.value || rejected.value)

function regenerateCandidate() {
  if (props.busy || !canRegenerate.value) return
  emit('regenerate')
}
```

Add optional `hasNextReviewCandidate` props and `continue-review: []` emits. For a rejected candidate, render:
- the existing `regenerate-candidate` button with `重新生成同题型候选题`;
- `continue-review-next-candidate` only when another pending draft exists;
- otherwise, `<NuxtLink data-testid="generate-new-ai-batch" to="/teacher/ai-questions/new">`.

In `TeacherAiReviewWorkspace.vue`, add:

```ts
const nextPendingDraft = computed(() => {
  const selected = selectedDraft.value
  if (!selected || selected.teacher_state !== 'rejected') return null
  const pending = drafts.value.filter(isPendingReview)
  return pending.find(draft => draft.ordinal > selected.ordinal) ?? pending[0] ?? null
})

function continueReview() {
  if (nextPendingDraft.value) return selectDraft(nextPendingDraft.value.id)
}
```

Pass `:has-next-review-candidate="nextPendingDraft !== null"` and `@continue-review="continueReview"` to the candidate component. Change only the regeneration guard to accept `rejected`; retain pending-only guards for save, accept, and reject.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
npm test -- --run tests/teacher-ai-review-rendering.test.ts tests/teacher-ai-review-presentation.test.ts
```

Expected: PASS, including rejected regeneration, explicit ordered continuation, new-batch fallback, and terminal immutability.

- [ ] **Step 7: Commit Task 1**

```powershell
git add apps/web/app/components/teacher/TeacherAiCandidateReview.vue apps/web/app/components/teacher/TeacherAiReviewWorkspace.vue apps/web/tests/teacher-ai-review-rendering.test.ts
git commit -m "fix: continue AI review after rejection"
```

### Task 2: Add browser coverage for rejected-teacher continuation

**Files:**
- Modify: `apps/web/e2e/teacher-ai-review.spec.ts`
- Test: `apps/web/e2e/teacher-ai-review.spec.ts`

**Interfaces:**
- Consumes: existing teacher E2E session helpers, generation-draft test ids, continuation test ids, and the regeneration endpoint.
- Produces: browser evidence that a rejected candidate does not trap the teacher and that the source draft stays rejected.

- [ ] **Step 1: Write the failing browser scenario**

Create or select a controlled pending source draft, reject it with `duplicate`, then assert:

```ts
await page.getByTestId('reject-candidate').click()
await expect(page.getByTestId('rejected-notice')).toContainText('已拒绝')
await expect(page.getByTestId('regenerate-candidate')).toBeVisible()
await expect(page.getByTestId('save-revision')).not.toBeAttached()
```

Wait for the regeneration POST after clicking the rejected action. Assert it returns a different job ID, the route switches to that job, and fetching the source batch still reports `teacher_state: 'rejected'`. For a two-candidate batch, click `continue-review-next-candidate` and assert the draft query changes to the next pending draft without an API POST.

- [ ] **Step 2: Verify RED**

Run:

```powershell
npx playwright test e2e/teacher-ai-review.spec.ts --project=chromium
```

Expected: FAIL because rejected candidates expose neither regeneration nor next-review continuation.

- [ ] **Step 3: Verify GREEN**

Run the same command after Task 1. Expected: PASS for existing scenarios plus rejected regeneration and explicit next-candidate continuation.

- [ ] **Step 4: Commit Task 2**

```powershell
git add apps/web/e2e/teacher-ai-review.spec.ts
git commit -m "test: cover AI rejection continuation"
```

### Task 3: Run final regression checks

**Files:**
- Verify only: `apps/web`

**Interfaces:**
- Consumes: Task 1 and Task 2 changes.
- Produces: a verified frontend artifact ready for review.

- [ ] **Step 1: Run all frontend tests**

```powershell
npm test
```

Expected: PASS with no failing test files.

- [ ] **Step 2: Run E2E API supervisor checks**

```powershell
node --test e2e/e2e-api-supervisor.test.mjs
```

Expected: PASS with all supervision tests green.

- [ ] **Step 3: Build production web**

```powershell
npm run build
```

Expected: exit code 0.

- [ ] **Step 4: Confirm scope**

```powershell
git status --short
git diff origin/main...HEAD --check
```

Expected: only approved rejection-continuation documentation, UI, tests, and browser coverage differ from `origin/main`.

