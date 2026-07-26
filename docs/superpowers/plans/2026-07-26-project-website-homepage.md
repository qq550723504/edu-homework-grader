# 项目官网首页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Nuxt 首页升级为可信、响应式的项目官网，并让学生和教师直接进入既有工作台。

**Architecture:** 首页仍是无数据依赖的 Nuxt 静态路由。`index.vue` 负责语义内容和既有路由链接，`main.css` 只新增 `.homepage` 限定样式，`nuxt.config.ts` 只更新静态元数据。Vitest 覆盖文案、结构与路由，Playwright 覆盖桌面和 320px 布局。

**Tech Stack:** Nuxt 4、Vue 3、CSS Grid、Vitest、Vue Test Utils、Playwright。

## Global Constraints

- 不新增 API、数据读取、认证、追踪、第三方组件、图片素材或远程字体。
- 使用 `NuxtLink`，学生与教师入口精确链接 `/student`、`/teacher`。
- 只陈述已实现的英语/数学作业、反馈、订正、教师复核与可追溯能力；不声称生产已上线或自动化替代教师判断。
- 新增样式必须以 `.homepage` 为根，不影响学生或教师工作台。
- 320px 下无页面横向溢出，角色入口为单列，主要链接最小高度为 44px。
- 不添加登录、注册、联系表单、虚构链接、客户徽标、数据指标、CMS 或多语言。

---

## File Structure

| 文件 | 责任 |
| --- | --- |
| `apps/web/app/pages/index.vue` | 官网语义结构、真实文案、站内锚点和双工作台入口。 |
| `apps/web/app/assets/css/main.css` | `.homepage` 限定的排版、网格、焦点与响应式规则。 |
| `apps/web/nuxt.config.ts` | 官网页面标题与描述。 |
| `apps/web/tests/homepage-rendering.test.ts` | 内容边界、语义结构和入口目标的快速回归。 |
| `apps/web/e2e/homepage.spec.ts` | Chromium 中的桌面和 320px 布局验收。 |

### Task 1: Lock the homepage contract with a failing unit test

**Files:**
- Modify: `apps/web/tests/homepage-rendering.test.ts`

**Interfaces:**
- Consumes: `HomePage` default export and `NuxtLink` `to` prop.
- Produces: the required IDs `#platform-capabilities`, `#trust-principles`, and the two workspace routes.

- [ ] **Step 1: Replace the old entry-page assertion with this test body**

```ts
it('presents the project website, trustworthy learning loop, and direct workspace entries', () => {
  const wrapper = mount(HomePage, {
    global: { stubs: { NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } },
  })

  expect(wrapper.get('header').text()).toContain('Edu Homework Grader')
  expect(wrapper.get('h1').text()).toBe('让作业、反馈与教学协作更清楚')
  expect(wrapper.get('a[href="/student"]').text()).toContain('进入学生工作台')
  expect(wrapper.get('a[href="/teacher"]').text()).toContain('进入教师工作台')
  expect(wrapper.get('#platform-capabilities').text()).toContain('英语与数学作业')
  expect(wrapper.get('#platform-capabilities').text()).toContain('订正')
  expect(wrapper.get('#trust-principles').text()).toContain('AI 辅助，不替代教师判断')
  expect(wrapper.text()).toContain('学生')
  expect(wrapper.text()).toContain('教师与学校')
  expect(wrapper.text()).toContain('家长')
  expect(wrapper.text()).not.toContain('Core API:')
  expect(wrapper.text()).not.toContain('生产已上线')
  wrapper.unmount()
})
```

Keep the current `beforeEach` and `afterEach` runtime-config setup. Do not call nonexistent Vue Test Utils accessibility helpers.

- [ ] **Step 2: Prove the test is red**

Run from `apps/web`:

```bash
npm test -- --run tests/homepage-rendering.test.ts
```

Expected: FAIL because the old page has neither `header` nor `#platform-capabilities`, and renders the old H1.

- [ ] **Step 3: Preserve the red test locally through Task 2**

Do not commit a knowingly failing test on `main`.

### Task 2: Implement the semantic, double-workspace homepage

**Files:**
- Modify: `apps/web/app/pages/index.vue`
- Modify: `apps/web/app/assets/css/main.css`
- Modify: `apps/web/nuxt.config.ts`

**Interfaces:**
- Consumes: `NuxtLink`, `/student`, and `/teacher`.
- Produces: `#platform-capabilities`, `#trust-principles`, `.homepage__role-grid`, `.homepage__student-entry`, `.homepage__teacher-entry`, and the final page title.

- [ ] **Step 1: Replace `index.vue` with this complete static template**

```vue
<template>
  <main class="homepage">
    <header class="homepage__header">
      <NuxtLink class="homepage__brand" to="/">Edu Homework Grader</NuxtLink>
      <nav class="homepage__nav" aria-label="官网导航">
        <a href="#platform-capabilities">平台能力</a><a href="#trust-principles">为什么可信</a>
        <NuxtLink class="button secondary" to="/student">进入学生工作台</NuxtLink>
        <NuxtLink class="button primary" to="/teacher">进入教师工作台</NuxtLink>
      </nav>
    </header>
    <section class="homepage__hero" aria-labelledby="homepage-title">
      <p class="eyebrow">英语与数学作业协作平台</p>
      <h1 id="homepage-title">让作业、反馈与教学协作更清楚</h1>
      <p class="lede">学生安心完成与订正，教师从容创建、跟进和复核，让每一步学习都有清晰的依据。</p>
      <div class="homepage__role-grid" aria-label="选择工作台">
        <article class="homepage__role-card homepage__student-entry"><p class="tag">学生</p><h2>完成作业，也读懂下一步</h2><p>查看学习任务、提交答案、获得反馈，并据此完成订正或申请复核。</p><NuxtLink class="button primary" to="/student">进入学生工作台</NuxtLink></article>
        <article class="homepage__role-card homepage__teacher-entry"><p class="tag">教师</p><h2>安排学习，也看见学习过程</h2><p>创建和布置任务、查看进展，及时处理需要专业判断的复核。</p><NuxtLink class="button secondary" to="/teacher">进入教师工作台</NuxtLink></article>
      </div>
    </section>
    <section class="homepage__section" aria-labelledby="audiences-title">
      <p class="eyebrow">为学习共同体而设计</p><h2 id="audiences-title">每个人都能看清学习正在发生什么</h2>
      <div class="homepage__audience-grid"><article><h3>学生</h3><p>把注意力放在作答、理解反馈和持续改进上。</p></article><article><h3>教师与学校</h3><p>用统一工作流连接出题、作业、学习进展与必要复核。</p></article><article><h3>家长</h3><p>通过清晰反馈理解孩子的学习过程与需要支持的地方。</p></article></div>
    </section>
    <section id="platform-capabilities" class="homepage__section homepage__section--tinted" aria-labelledby="capabilities-title">
      <p class="eyebrow">平台能力</p><h2 id="capabilities-title">从作业到订正，学习过程有迹可循</h2>
      <ol class="homepage__journey"><li><strong>01</strong><div><h3>英语与数学作业</h3><p>围绕课程任务完成在线作答。</p></div></li><li><strong>02</strong><div><h3>规则化反馈</h3><p>让每次作答获得稳定、可理解的反馈。</p></div></li><li><strong>03</strong><div><h3>教师复核</h3><p>把需要理解语境与专业判断的结果交给教师。</p></div></li><li><strong>04</strong><div><h3>订正与申诉</h3><p>学生根据反馈订正，并在需要时提出复核申请。</p></div></li></ol>
    </section>
    <section id="trust-principles" class="homepage__section" aria-labelledby="trust-title">
      <p class="eyebrow">为什么可信</p><h2 id="trust-title">技术辅助教学，但不取代教育判断</h2>
      <div class="homepage__trust-grid"><article><h3>一致的评分规则</h3><p>基础题以明确规则提供稳定判断依据。</p></article><article><h3>AI 辅助，不替代教师判断</h3><p>需要理解语境的结果保留给教师复核。</p></article><article><h3>反馈可追溯</h3><p>学生、教师都能回看反馈与后续处理。</p></article></div>
    </section>
    <footer class="homepage__footer"><div><p class="eyebrow">现在开始</p><h2>进入适合你的工作台</h2></div><div class="homepage__footer-actions"><NuxtLink class="button secondary" to="/student">进入学生工作台</NuxtLink><NuxtLink class="button primary" to="/teacher">进入教师工作台</NuxtLink></div></footer>
  </main>
</template>
```

- [ ] **Step 2: Replace the old homepage CSS selectors with this scoped style**

Delete `.homepage .hero`, `.role-grid`, `.role-card`, `.trust-section`, `.trust-grid`. Keep the existing global color, typography, `.button`, `.eyebrow`, `.lede`, and `.tag` primitives. Add:

```css
.homepage { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 22px 0 48px; }
.homepage__header, .homepage__nav, .homepage__footer, .homepage__footer-actions { display: flex; align-items: center; }
.homepage__header { justify-content: space-between; gap: 24px; padding: 10px 0 34px; }
.homepage__brand { color: #152033; font-size: 1.08rem; font-weight: 850; letter-spacing: -.03em; text-decoration: none; }
.homepage__nav { justify-content: flex-end; flex-wrap: wrap; gap: 10px; }.homepage__nav > a:not(.button) { padding: 10px 8px; color: #526176; font-size: .9rem; font-weight: 750; text-decoration: none; }
.homepage__hero { padding: clamp(28px, 6vw, 70px) 0; }.homepage__hero > .lede { max-width: 690px; }
.homepage__role-grid, .homepage__audience-grid, .homepage__trust-grid { display: grid; gap: 18px; }.homepage__role-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 42px; }
.homepage__role-card { display: flex; min-height: 285px; flex-direction: column; padding: clamp(24px, 4vw, 36px); border: 1px solid #e1e7f0; border-radius: 20px; background: #fff; box-shadow: 0 14px 32px rgba(27, 45, 78, .07); }.homepage__role-card h2 { margin: 16px 0 10px; font-size: clamp(1.45rem, 2.5vw, 2rem); }.homepage__role-card p:not(.tag) { margin: 0; color: #667085; line-height: 1.7; }.homepage__role-card .button { align-self: flex-start; margin-top: auto; }
.homepage__section { padding: clamp(56px, 9vw, 104px) 0; scroll-margin-top: 20px; }.homepage__section > h2, .homepage__footer h2 { max-width: 690px; margin: 0; font-size: clamp(1.8rem, 4vw, 3rem); letter-spacing: -.04em; }.homepage__audience-grid, .homepage__trust-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 32px; }.homepage__audience-grid article, .homepage__trust-grid article { padding: 22px; border-top: 2px solid #dbe6fb; }.homepage__audience-grid h3, .homepage__trust-grid h3, .homepage__journey h3 { margin: 0 0 8px; font-size: 1.05rem; }.homepage__audience-grid p, .homepage__trust-grid p, .homepage__journey p { margin: 0; color: #667085; line-height: 1.65; }
.homepage__section--tinted { margin-inline: calc((100vw - min(1180px, calc(100vw - 32px))) / -2); padding-inline: max(16px, calc((100vw - min(1180px, calc(100vw - 32px))) / 2)); background: #eaf1ff; }.homepage__journey { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; padding: 0; margin: 34px 0 0; list-style: none; }.homepage__journey li { display: grid; gap: 16px; padding: 22px 0; border-top: 1px solid #bdd0f6; }.homepage__journey strong { color: #2459c4; font-size: .8rem; letter-spacing: .1em; }
.homepage__footer { justify-content: space-between; gap: 24px; padding: 38px; border-radius: 20px; background: #14284a; color: #fff; }.homepage__footer .eyebrow { color: #9ebcf7; }.homepage__footer-actions { flex-wrap: wrap; gap: 12px; }.homepage :focus-visible { outline: 3px solid rgba(45, 99, 216, .4); outline-offset: 3px; }
@media (max-width: 760px) { .homepage { padding-top: 12px; }.homepage__header, .homepage__footer { align-items: flex-start; flex-direction: column; }.homepage__nav { justify-content: flex-start; }.homepage__role-grid, .homepage__audience-grid, .homepage__trust-grid, .homepage__journey { grid-template-columns: 1fr; }.homepage__role-card { min-height: 0; }.homepage__role-card .button, .homepage__footer-actions, .homepage__footer-actions .button { width: 100%; }.homepage__footer { padding: 28px 24px; } }
```

- [ ] **Step 3: Update only `app.head` in `nuxt.config.ts`**

```ts
title: 'Edu Homework Grader｜作业、反馈与教学协作平台',
meta: [{
  name: 'description',
  content: '面向学生、教师与学校的英语和数学作业协作平台，连接作业、反馈、教师复核与订正。',
}],
```

Do not change `runtimeConfig`, Vite optimization, compatibility date, or devtools.

- [ ] **Step 4: Verify Task 1 is green and build succeeds**

Run from `apps/web`:

```bash
npm test -- --run tests/homepage-rendering.test.ts
npm run build
```

Expected: both commands exit `0`.

- [ ] **Step 5: Commit the implementation and unit contract**

```bash
git add apps/web/app/pages/index.vue apps/web/app/assets/css/main.css apps/web/nuxt.config.ts apps/web/tests/homepage-rendering.test.ts
git commit -m "feat: build project website homepage"
```

### Task 3: Add desktop and 320px browser acceptance

**Files:**
- Create: `apps/web/e2e/homepage.spec.ts`

**Interfaces:**
- Consumes: the DOM IDs, CSS classes, title, and accessible link names produced by Task 2.
- Produces: a browser regression gate; no production API interface.

- [ ] **Step 1: Write this Playwright test**

```ts
import { expect, test } from '@playwright/test'

test('homepage presents both workspace entries and the trustworthy learning loop on desktop', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Edu Homework Grader｜作业、反馈与教学协作平台')
  await expect(page.getByRole('heading', { name: '让作业、反馈与教学协作更清楚' })).toBeVisible()
  await expect(page.getByRole('link', { name: '进入学生工作台' }).first()).toHaveAttribute('href', '/student')
  await expect(page.getByRole('link', { name: '进入教师工作台' }).first()).toHaveAttribute('href', '/teacher')
  await expect(page.getByRole('heading', { name: '从作业到订正，学习过程有迹可循' })).toBeVisible()
  await expect(page.getByText('AI 辅助，不替代教师判断')).toBeVisible()
  const [student, teacher] = await Promise.all([page.locator('.homepage__student-entry').boundingBox(), page.locator('.homepage__teacher-entry').boundingBox()])
  expect(student).not.toBeNull(); expect(teacher).not.toBeNull(); expect(Math.abs(student!.y - teacher!.y)).toBeLessThan(8)
})

test('homepage remains single-column and without horizontal overflow at 320px', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 320, height: 720 } }); const page = await context.newPage()
  try {
    await page.goto('/')
    const [student, teacher] = await Promise.all([page.locator('.homepage__student-entry').boundingBox(), page.locator('.homepage__teacher-entry').boundingBox()])
    expect(student).not.toBeNull(); expect(teacher).not.toBeNull(); expect(teacher!.y).toBeGreaterThan(student!.y + student!.height)
    await expect(page.getByRole('link', { name: '进入学生工作台' }).first()).toHaveCSS('min-height', '44px')
    await expect(page.getByRole('link', { name: '进入教师工作台' }).first()).toHaveCSS('min-height', '44px')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  } finally { await context.close() }
})
```

- [ ] **Step 2: Run the focused browser verification**

Run from `apps/web`:

```bash
npx playwright test e2e/homepage.spec.ts --project=chromium
```

Expected: both tests pass; the existing Playwright config starts its isolated API and Nuxt server.

- [ ] **Step 3: Run the complete Web regression and inspect the responsive result**

```bash
npm test
npm run build
npx playwright test e2e/homepage.spec.ts --project=chromium
```

Inspect the desktop pair, 320px vertical stack, visible focus indicators, and footer actions. Expected: all commands exit `0`, with no horizontal overflow.

- [ ] **Step 4: Commit the browser regression gate**

```bash
git add apps/web/e2e/homepage.spec.ts
git commit -m "test: cover project website homepage"
```

## Plan Self-Review

- **Spec coverage:** Task 2 implements navigation, dual roles, three audiences, learning loop, trust section, repeated actions, metadata, and scoped responsiveness. Tasks 1 and 3 guard content, routing, desktop layout, and mobile behavior.
- **Placeholder scan:** no unresolved markers, undefined interfaces, or deferred implementation steps remain.
- **Type consistency:** all selector names, IDs, titles, text labels, and `/student`/`/teacher` route strings match across the tasks.
