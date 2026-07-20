# Teacher Workbench Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the teacher landing page with a responsive, module-oriented workbench that includes overview, question-bank, and assignment-creation layouts.

**Architecture:** Keep the page route as the coordinator, but move navigation labels and form-completeness rules into a typed UI helper so the page and tests share one contract. Use focused Vue components for the shell navigation, overview, question workspace, and assignment workspace; each workspace owns its local form state and emits only navigation requests to the route. Keep all data static/local in this slice: no API request, backend model, or authentication contract changes.

**Tech Stack:** Nuxt 4, Vue 3 `<script setup lang="ts">`, CSS Grid/Flexbox, Vitest 4.

## Global Constraints

- Do not change API routes, request payloads, database models, grading policy, or authentication.
- Preserve the `/teacher` route and use semantic native buttons, labels, inputs, textareas, and selects.
- Keep interactive controls keyboard reachable with visible `:focus-visible` treatment and 44px minimum action height.
- Use mobile-first CSS; the shell must have no horizontal overflow at 320px wide.
- Do not add dependencies; existing Nuxt, Vue, and Vitest packages are sufficient.

---

## File Structure

- Create: `apps/web/app/lib/teacher-workbench.ts` — typed navigation model and pure validation helpers.
- Create: `apps/web/tests/teacher-workbench.test.ts` — unit coverage for module identity and creation-form readiness.
- Create: `apps/web/app/components/teacher/TeacherWorkbenchNav.vue` — semantic desktop sidebar and compact mobile module navigation.
- Create: `apps/web/app/components/teacher/TeacherOverview.vue` — metrics, priority actions, and quick-start cards.
- Create: `apps/web/app/components/teacher/TeacherQuestionWorkspace.vue` — question empty state and structured question form.
- Create: `apps/web/app/components/teacher/TeacherAssignmentWorkspace.vue` — assignment empty state and structured assignment form.
- Modify: `apps/web/app/pages/teacher/index.vue` — page shell, active-module state, and module composition.
- Modify: `apps/web/app/assets/css/main.css` — page-scoped workbench layout, form, focus, and responsive styles.

### Task 1: Define and test the teacher-workbench UI contract

**Files:**

- Create: `apps/web/app/lib/teacher-workbench.ts`
- Test: `apps/web/tests/teacher-workbench.test.ts`

**Interfaces:**

- Produces: `TeacherModule`, `teacherModules`, `isQuestionDraftReady`, and `isAssignmentDraftReady` for the page and workspace components.
- Consumes: no runtime service or API data.

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/teacher-workbench.test.ts` with the exact coverage below:

```ts
import { describe, expect, it } from 'vitest'

import {
  isAssignmentDraftReady,
  isQuestionDraftReady,
  teacherModules
} from '../app/lib/teacher-workbench'

describe('teacher workbench UI contract', () => {
  it('exposes the five stable teacher modules in navigation order', () => {
    expect(teacherModules.map((module) => module.id)).toEqual([
      'overview', 'reviews', 'questions', 'assignments', 'requests'
    ])
  })

  it('requires the visible question creation fields', () => {
    expect(isQuestionDraftReady({ title: '', prompt: '计算 2 + 3', questionType: 'math', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '   ', questionType: 'math', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '计算 2 + 3', questionType: '', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '计算 2 + 3', questionType: 'math', answer: '5' })).toBe(true)
  })

  it('requires the visible assignment creation fields', () => {
    expect(isAssignmentDraftReady({ title: '周末练习', className: '', dueAt: '2026-07-21T18:00', allowLate: false })).toBe(false)
    expect(isAssignmentDraftReady({ title: '周末练习', className: '三年级 2 班', dueAt: '', allowLate: false })).toBe(false)
    expect(isAssignmentDraftReady({ title: '周末练习', className: '三年级 2 班', dueAt: '2026-07-21T18:00', allowLate: true })).toBe(true)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
```

Expected: FAIL because `../app/lib/teacher-workbench` does not exist.

- [ ] **Step 3: Write the minimal UI contract implementation**

Create `apps/web/app/lib/teacher-workbench.ts` with:

```ts
export type TeacherModule = 'overview' | 'reviews' | 'questions' | 'assignments' | 'requests'

export interface QuestionDraft {
  title: string
  prompt: string
  questionType: string
  answer: string
}

export interface AssignmentDraft {
  title: string
  className: string
  dueAt: string
  allowLate: boolean
}

export const teacherModules: ReadonlyArray<{ id: TeacherModule; label: string; badge?: string }> = [
  { id: 'overview', label: '工作台' },
  { id: 'reviews', label: '复核队列', badge: '36' },
  { id: 'questions', label: '题库' },
  { id: 'assignments', label: '作业' },
  { id: 'requests', label: '学生申请', badge: '2' }
]

export function isQuestionDraftReady(draft: QuestionDraft): boolean {
  return [draft.title, draft.prompt, draft.questionType, draft.answer].every((value) => value.trim().length > 0)
}

export function isAssignmentDraftReady(draft: AssignmentDraft): boolean {
  return [draft.title, draft.className, draft.dueAt].every((value) => value.trim().length > 0)
}
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
```

Expected: PASS with 3 passing tests.

- [ ] **Step 5: Commit the contract slice**

```powershell
git add apps/web/app/lib/teacher-workbench.ts apps/web/tests/teacher-workbench.test.ts
git commit -m "feat(web): add teacher workbench UI contract"
```

### Task 2: Build the workbench shell and overview module

**Files:**

- Create: `apps/web/app/components/teacher/TeacherWorkbenchNav.vue`
- Create: `apps/web/app/components/teacher/TeacherOverview.vue`
- Modify: `apps/web/app/pages/teacher/index.vue`
- Modify: `apps/web/app/assets/css/main.css`

**Interfaces:**

- Consumes: `TeacherModule` and `teacherModules` from `~/app/lib/teacher-workbench`.
- Produces: `select` events from `TeacherWorkbenchNav` and `open-module` events from `TeacherOverview`, both carrying a `TeacherModule`.

- [ ] **Step 1: Extend the failing contract test for the overview targets**

Append this assertion to `apps/web/tests/teacher-workbench.test.ts`:

```ts
it('keeps every overview action addressable by a navigation module', () => {
  const ids = new Set(teacherModules.map((module) => module.id))
  expect(ids.has('reviews')).toBe(true)
  expect(ids.has('questions')).toBe(true)
  expect(ids.has('assignments')).toBe(true)
  expect(ids.has('requests')).toBe(true)
})
```

- [ ] **Step 2: Run the focused test before the UI integration**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
```

Expected: PASS; this guards the module names that template events will use.

- [ ] **Step 3: Create the navigation and overview components**

`TeacherWorkbenchNav.vue` must accept `activeModule: TeacherModule` and emit `select` with a `TeacherModule`. Its core template must remain semantic:

```vue
<nav class="teacher-nav" aria-label="教师工作区">
  <button
    v-for="module in teacherModules"
    :key="module.id"
    class="teacher-nav__item"
    :class="{ 'teacher-nav__item--active': activeModule === module.id }"
    type="button"
    :aria-current="activeModule === module.id ? 'page' : undefined"
    @click="$emit('select', module.id)"
  >
    <span>{{ module.label }}</span>
    <span v-if="module.badge" class="teacher-nav__badge">{{ module.badge }}</span>
  </button>
</nav>
```

`TeacherOverview.vue` must show the three existing metrics (`36`, `82%`, `4`), review and request actions, and buttons that emit `open-module` for `questions` and `assignments`. Use no `<a href="#">` placeholders.

- [ ] **Step 4: Replace the page with the active-module shell**

In `apps/web/app/pages/teacher/index.vue`, import `TeacherModule`, `TeacherWorkbenchNav`, and `TeacherOverview`; initialize `const activeModule = ref<TeacherModule>('overview')`; and render the top bar, navigation, and overview conditionally. The shell must use this event wiring:

```vue
<TeacherWorkbenchNav :active-module="activeModule" @select="activeModule = $event" />
<TeacherOverview v-if="activeModule === 'overview'" @open-module="activeModule = $event" />
```

For `reviews` and `requests`, render a titled empty-state card that tells the teacher that the module will contain its corresponding queue. Do not manufacture review data or API calls.

- [ ] **Step 5: Add the shell and overview CSS**

In `apps/web/app/assets/css/main.css`, add a `teacher-workbench` block with a 236px sidebar, a flexible content column, a top bar, three auto-fit metric cards, and 44px action buttons. At `max-width: 760px`, change the shell to one column and set `.teacher-nav` to `display: flex; overflow-x: auto;` with each item `flex: 0 0 auto`; do not hide the module labels.

- [ ] **Step 6: Verify and commit the shell slice**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
npm run build
git add apps/web/app/components/teacher/TeacherWorkbenchNav.vue apps/web/app/components/teacher/TeacherOverview.vue apps/web/app/pages/teacher/index.vue apps/web/app/assets/css/main.css apps/web/tests/teacher-workbench.test.ts
git commit -m "feat(web): add teacher workbench shell"
```

Expected: all focused tests pass and Nuxt completes the production build.

### Task 3: Add the question-bank workspace and form

**Files:**

- Create: `apps/web/app/components/teacher/TeacherQuestionWorkspace.vue`
- Modify: `apps/web/app/pages/teacher/index.vue`
- Modify: `apps/web/app/assets/css/main.css`

**Interfaces:**

- Consumes: `QuestionDraft` and `isQuestionDraftReady` from `~/app/lib/teacher-workbench`.
- Produces: local visual draft state only; this slice does not perform a `POST /v1/questions` request.

- [ ] **Step 1: Add the question form's disabled-state assertion**

Append this test to `apps/web/tests/teacher-workbench.test.ts`:

```ts
it('rejects whitespace-only question answers', () => {
  expect(isQuestionDraftReady({
    title: '加法练习', prompt: '计算 2 + 3', questionType: 'math', answer: '   '
  })).toBe(false)
})
```

- [ ] **Step 2: Run the test to verify the current helper already protects the UI boundary**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
```

Expected: PASS because the implementation rejects all whitespace-only visible fields.

- [ ] **Step 3: Create the question workspace**

Create `TeacherQuestionWorkspace.vue` with local state:

```ts
const draft = reactive<QuestionDraft>({ title: '', prompt: '', questionType: 'math', answer: '' })
const attemptedSubmit = ref(false)
const ready = computed(() => isQuestionDraftReady(draft))
const submit = () => { attemptedSubmit.value = true }
```

Render a `section.teacher-workspace` with a question-bank empty state followed by a `<form @submit.prevent="submit">`. Include labels and controls for `题目标题`, `题干`, `题型`, and `正确答案`; make title, prompt, and answer `required`; bind the submit button with `:disabled="!ready"`; and render `请补全题目标题、题干与正确答案。` in a `role="alert"` only after a submit attempt with an incomplete draft. The select must offer `math` as `数值题` and `text` as `文本题`.

- [ ] **Step 4: Mount the question workspace from the route**

Import `TeacherQuestionWorkspace` into `apps/web/app/pages/teacher/index.vue` and add:

```vue
<TeacherQuestionWorkspace v-else-if="activeModule === 'questions'" />
```

Place it after the overview condition and before the fallback request/review empty state.

- [ ] **Step 5: Add two-column form layout CSS**

Add `.teacher-workspace` as a grid with `grid-template-columns: minmax(220px, .8fr) minmax(0, 1.2fr)`, `.teacher-form` as a grid with 14px gaps, and `.teacher-field > label` as a block label above every control. Inputs, selects, and textareas must use `width: 100%`, a minimum height of 44px, and `resize: vertical` for the prompt textarea. At `max-width: 760px`, set `.teacher-workspace { grid-template-columns: 1fr; }`.

- [ ] **Step 6: Verify and commit the question workspace slice**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
npm run build
git add apps/web/app/components/teacher/TeacherQuestionWorkspace.vue apps/web/app/pages/teacher/index.vue apps/web/app/assets/css/main.css apps/web/tests/teacher-workbench.test.ts
git commit -m "feat(web): add teacher question workspace"
```

Expected: all focused tests pass and the Nuxt build succeeds.

### Task 4: Add the assignments workspace and complete responsive verification

**Files:**

- Create: `apps/web/app/components/teacher/TeacherAssignmentWorkspace.vue`
- Modify: `apps/web/app/pages/teacher/index.vue`
- Modify: `apps/web/app/assets/css/main.css`
- Test: `apps/web/tests/teacher-workbench.test.ts`

**Interfaces:**

- Consumes: `AssignmentDraft` and `isAssignmentDraftReady` from `~/app/lib/teacher-workbench`.
- Produces: local visual draft state only; it deliberately does not call `POST /v1/assignments` until class and question-version selection data are available.

- [ ] **Step 1: Add the late-submission readiness test**

Append this test to `apps/web/tests/teacher-workbench.test.ts`:

```ts
it('does not make late-submission choice a prerequisite for an assignment draft', () => {
  const base = { title: '周末练习', className: '三年级 2 班', dueAt: '2026-07-21T18:00' }
  expect(isAssignmentDraftReady({ ...base, allowLate: false })).toBe(true)
  expect(isAssignmentDraftReady({ ...base, allowLate: true })).toBe(true)
})
```

- [ ] **Step 2: Run the focused test**

Run:

```powershell
npm test -- --run tests/teacher-workbench.test.ts
```

Expected: PASS with the optional late-submission choice accepted in both states.

- [ ] **Step 3: Create the assignment workspace**

Create `TeacherAssignmentWorkspace.vue` with:

```ts
const draft = reactive<AssignmentDraft>({ title: '', className: '', dueAt: '', allowLate: false })
const attemptedSubmit = ref(false)
const ready = computed(() => isAssignmentDraftReady(draft))
const submit = () => { attemptedSubmit.value = true }
```

Render an assignment empty state and a semantic form with labels for `作业标题`, `班级`, `题目版本`, and `截止时间`, plus a labelled checkbox `允许迟交`. Use a disabled select for `题目版本` with the single option `暂无已发布题目` so the UI does not imply that a missing list endpoint exists. Render an alert after a submit attempt with missing title, class, or deadline; the disabled primary submit uses the label `创建作业草稿`.

- [ ] **Step 4: Mount the assignment workspace and retain fallback modules**

In `apps/web/app/pages/teacher/index.vue`, import `TeacherAssignmentWorkspace` and add:

```vue
<TeacherAssignmentWorkspace v-else-if="activeModule === 'assignments'" />
```

Keep a shared empty-state branch for `reviews` and `requests`, with copy based on `activeModule` and no simulated queue rows.

- [ ] **Step 5: Add final accessibility and small-screen CSS**

Add visible focus styles for `.teacher-nav__item`, `.teacher-form input`, `.teacher-form textarea`, `.teacher-form select`, and `.teacher-form button`:

```css
.teacher-workbench :focus-visible {
  outline: 3px solid rgba(45, 99, 216, .35);
  outline-offset: 2px;
}
```

At `max-width: 760px`, reduce outer workbench padding to 16px, keep the top-bar actions wrapping, make metric cards one column, and make every primary form action full-width. Verify that the form uses no fixed input width.

- [ ] **Step 6: Run full automated verification**

Run:

```powershell
npm test
npm run build
```

Expected: Vitest reports all tests passing and Nuxt finishes without template, TypeScript, or CSS build errors.

- [ ] **Step 7: Run manual viewport verification**

Run the development server:

```powershell
npm run dev
```

Verify `/teacher` at 1440px and 320px wide:

- the desktop sidebar remains visible, the metrics are three columns, and question/assignment workspaces are two columns;
- mobile navigation is horizontally scrollable, not clipped; metrics and workspaces stack; primary actions remain visible and at least 44px tall;
- switching to 题库 and 作业 exposes the respective form; incomplete visible fields keep the submit button disabled;
- no page-level horizontal scrollbar appears.

- [ ] **Step 8: Commit the final workspace slice**

```powershell
git add apps/web/app/components/teacher/TeacherAssignmentWorkspace.vue apps/web/app/pages/teacher/index.vue apps/web/app/assets/css/main.css apps/web/tests/teacher-workbench.test.ts
git commit -m "feat(web): add teacher assignment workspace"
```
