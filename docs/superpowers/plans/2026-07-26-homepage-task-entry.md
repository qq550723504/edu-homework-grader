# Homepage Task-Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the public homepage into a clear student and teacher task-entry page while preserving existing role routing.

**Architecture:** Keep the homepage as a self-contained Nuxt page with static role-entry copy and existing `NuxtLink` destinations. Add a focused rendering test that mounts the page with a link stub, then update the existing shared CSS only for homepage layout and keyboard-focus treatment.

**Tech Stack:** Nuxt 4, Vue 3, TypeScript, Vitest, Vue Test Utils, shared CSS.

## Global Constraints

- Keep `/student` and `/teacher` as the only homepage workspace destinations.
- Do not fetch session data or change authentication, redirects, or role permissions.
- Do not introduce an administrator entry or API calls on the homepage.
- Retain the existing blue, white-card, responsive visual system.
- Keep primary touch targets at least 44px tall and provide a visible `:focus-visible` state.

---

### Task 1: Cover the public role-entry experience

**Files:**
- Create: `apps/web/tests/homepage-rendering.test.ts`
- Modify: `apps/web/app/pages/index.vue`

**Interfaces:**
- Consumes: Nuxt `NuxtLink` with its existing `to` prop.
- Produces: Static public homepage content with one student link to `/student` and one teacher link to `/teacher`.

- [ ] **Step 1: Write the failing test**

```ts
// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import HomePage from '../app/pages/index.vue'
import '../app/assets/css/main.css'

describe('homepage task entry', () => {
  it('guides students and teachers to their respective workspaces without exposing the API URL', () => {
    const wrapper = mount(HomePage, {
      global: {
        stubs: {
          NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
        },
      },
    })

    expect(wrapper.get('h1').text()).toBe('开始你的作业与教学工作')
    expect(wrapper.get('a[href="/student"]').text()).toBe('查看我的作业')
    expect(wrapper.get('a[href="/teacher"]').text()).toBe('进入教学工作台')
    expect(wrapper.text()).toContain('待完成作业')
    expect(wrapper.text()).toContain('创建作业')
    expect(wrapper.text()).toContain('为什么值得信赖')
    expect(wrapper.text()).not.toContain('Core API:')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm.cmd exec vitest run tests/homepage-rendering.test.ts`

Expected: FAIL because the old homepage heading, action labels, and API footer do not meet the new task-entry contract.

- [ ] **Step 3: Write minimal implementation**

Replace the homepage hero in `apps/web/app/pages/index.vue` with a public task-entry heading and short description. Add two `article` elements inside a role-entry section:

```vue
<article class="role-card">
  <p class="tag">学生</p>
  <h2>先完成今天的学习任务</h2>
  <p>查看待完成作业，提交答案，并按反馈完成订正。</p>
  <NuxtLink class="button primary" to="/student">查看我的作业</NuxtLink>
</article>
```

Add the equivalent teacher card with the `/teacher` destination and the label `进入教学工作台`. Replace the technical capability cards with the heading `为什么值得信赖` and concise, user-facing assurances. Remove `useRuntimeConfig` and the API URL footer; render a non-technical product-status footer instead.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm.cmd exec vitest run tests/homepage-rendering.test.ts`

Expected: PASS with one homepage task-entry test passing.

- [ ] **Step 5: Commit**

```bash
git add apps/web/tests/homepage-rendering.test.ts apps/web/app/pages/index.vue
git commit -m "feat: clarify homepage task entry"
```

### Task 2: Style role entries, trust section, and keyboard focus

**Files:**
- Modify: `apps/web/app/assets/css/main.css`

**Interfaces:**
- Consumes: Homepage classes `role-grid`, `role-card`, and `trust-grid` from `index.vue`.
- Produces: Responsive two-column role entry layout, one-column narrow-screen layout, and visible keyboard focus treatment.

- [ ] **Step 1: Keep styling scoped to the public homepage**

Do not add a source-text or simulated-CSS assertion: the existing unit runner
does not reliably compute imported stylesheet layout. Verify responsive layout
and focus appearance in a real local browser during Task 3.

- [ ] **Step 2: Write minimal implementation**

Add a `.homepage` scope to the page root, a two-column `.role-grid`, white
`.role-card` panels, and a three-column `.trust-grid` that uses the existing
card treatment. Add:

```css
.homepage :focus-visible {
  outline: 3px solid rgba(45, 99, 216, .4);
  outline-offset: 3px;
}
```

At the existing 760px breakpoint, set `.role-grid` and `.trust-grid` to one
column and make the role-card action links full width. Do not change shared
student or teacher layout rules.

- [ ] **Step 3: Run the focused rendering test and inspect focus visually**

Run: `node node_modules/vitest/vitest.mjs run tests/homepage-rendering.test.ts`

Expected: The task-entry content assertions pass. During
the final local browser check, tab to each homepage action and confirm the
visible blue focus outline is not obscured by the card or button.

- [ ] **Step 4: Commit**

```bash
git add apps/web/app/assets/css/main.css
git commit -m "style: improve homepage task entry"
```

### Task 3: Verify the integrated web application

**Files:**
- Verify only: `apps/web/tests/homepage-rendering.test.ts`, `apps/web/app/pages/index.vue`, `apps/web/app/assets/css/main.css`

**Interfaces:**
- Consumes: the completed public homepage and shared web test configuration.
- Produces: verification evidence for the static homepage change.

- [ ] **Step 1: Run the full web test suite**

Run: `pnpm.cmd test`

Expected: PASS with no test failures.

- [ ] **Step 2: Build the Nuxt application**

Run: `pnpm.cmd build`

Expected: EXIT 0; Nuxt compiles the updated page and shared CSS.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff main...HEAD --check && git diff main...HEAD -- apps/web/app/pages/index.vue apps/web/app/assets/css/main.css apps/web/tests/homepage-rendering.test.ts`

Expected: No whitespace errors and changes confined to the homepage, its focused test, styling, and the approved documentation.

- [ ] **Step 4: Commit any verification-only correction**

If verification requires a correction, repeat the relevant task's red-green cycle before committing it. Otherwise make no commit in this step.
