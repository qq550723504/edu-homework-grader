# Teacher roster entry implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task.

**Goal:** Make the existing class and student roster workflow directly discoverable from the teacher workbench.

**Architecture:** Add a `roster` workbench module that reuses the existing roster form on the teacher page. Give the workbench overview and navigation direct links to that module; do not duplicate API calls or forms.

**Tech Stack:** Nuxt 4, Vue 3, Vitest, Playwright.

## Task 1: Expose the existing roster flow

**Files:**
- Modify: `apps/web/app/lib/teacher-workbench.ts`
- Modify: `apps/web/app/components/teacher/TeacherWorkbenchNav.vue`
- Modify: `apps/web/app/components/teacher/TeacherOverview.vue`
- Modify: `apps/web/app/pages/teacher/index.vue`
- Test: `apps/web/tests/teacher-workbench.test.ts`

- [ ] Write a failing source-contract test requiring the `roster` module, navigation label `班级名册`, overview action, and roster-only page section.
- [ ] Run `npm test -- teacher-workbench.test.ts` and confirm failure.
- [ ] Add the `roster` module, render the existing roster section only while it is active, and link overview/nav actions to it.
- [ ] Run `npm test -- teacher-workbench.test.ts` and `npm run build`.
- [ ] Run `npx playwright test` and commit the focused change.
