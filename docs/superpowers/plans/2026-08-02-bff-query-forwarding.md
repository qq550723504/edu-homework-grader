# BFF Query Forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve query parameters through the authenticated Nuxt BFF so Core API filters, including teacher review filters, work in production.

**Architecture:** Add one E2E regression test against the real Nuxt BFF and the existing isolated Core API fixture. Change only the BFF's upstream URL construction to append the H3 request query string, while retaining the current path validation, bearer-token injection, CSRF checks, header filtering, methods, and response propagation.

**Tech Stack:** Nuxt 4/Nitro, H3, TypeScript, Playwright, Vitest.

## Global Constraints

- Do not alter Core API filtering, review-task data, authentication ownership, or CSRF policy.
- Do not log, return, or persist access tokens, session cookies, activation codes, passwords, or other credentials.
- Query-less BFF requests must retain their current upstream URL.
- Validate in the local isolated E2E environment before any PR or production deployment decision.

---

## File Structure

- `apps/web/server/api/core/[...path].ts`: authenticated BFF proxy; append the incoming query string to its upstream URL.
- `apps/web/e2e/core-api-query-forwarding.spec.ts`: E2E regression test that creates two teacher-owned questions and asserts a query through the BFF returns only the uniquely matching question.

### Task 1: Lock the proxy behavior with an E2E regression test

**Files:**
- Create: `apps/web/e2e/core-api-query-forwarding.spec.ts`

**Interfaces:**
- Consumes `POST /api/auth/e2e-session` with `X-E2E-Token: e2e-teacher-token` to establish a BFF session.
- Consumes `POST /api/core/v1/questions` and `GET /api/core/v1/questions?query=<unique phrase>` through that session.
- Produces a regression assertion that the returned `question_versions` contain the unique title and exclude a second title.

- [ ] **Step 1: Write the failing E2E test**

```ts
test('forwards query parameters to the Core API', async ({ page }) => {
  await establishTeacherSession(page)
  const marker = `BFF query ${Date.now()}`
  await createQuestion(page, `${marker} match`)
  await createQuestion(page, `${marker} other`)

  const response = await page.request.get(
    `${webBaseUrl}/api/core/v1/questions?query=${encodeURIComponent(`${marker} match`)}`,
  )
  await expectOk(response, 'filter questions through the BFF')
  const payload = await response.json() as { question_versions: Array<{ title: string }> }
  expect(payload.question_versions.map((question) => question.title)).toEqual([`${marker} match`])
})
```

The helper uses the existing E2E teacher session pattern, obtains its CSRF token from `/api/auth/session`, and creates published-independent M1 question drafts with `question_type: 'M1'`, `prompt: marker`, `policy_version: '1'`, and `rule: { expected: 4 }`.

- [ ] **Step 2: Run the focused test and verify red**

Run: `npm.cmd --prefix apps/web run test:e2e -- --grep "forwards query parameters to the Core API"`

Expected: FAIL because the BFF fetches `/v1/questions` without `?query=...`, so both newly created questions are returned.

- [ ] **Step 3: Commit the failing-test checkpoint only if the repository workflow requires it**

Run: `git status --short`

Do not commit an intentionally failing test to the shared branch unless the user specifically requests a red-test checkpoint.

### Task 2: Preserve the H3 request query string in the BFF upstream URL

**Files:**
- Modify: `apps/web/server/api/core/[...path].ts`
- Test: `apps/web/e2e/core-api-query-forwarding.spec.ts`

**Interfaces:**
- Consumes `getRequestURL(event).search` from H3.
- Produces a Core API URL in the form `${coreApiBase}/${path}${getRequestURL(event).search}`.

- [ ] **Step 1: Implement the minimal proxy change**

```ts
import { getRequestHeaders, getRequestURL, getRouterParam, readRawBody, setResponseHeader, setResponseStatus } from 'h3'

// after validating path and building headers
const upstreamUrl = `${config.coreApiBase.replace(/\/$/, '')}/${path}${getRequestURL(event).search}`
const response = await fetch(upstreamUrl, {
  body: ['GET', 'HEAD'].includes(event.method ?? 'GET') ? undefined : await readRawBody(event, false),
  headers,
  method: event.method,
})
```

Do not change the existing path validation or any request/response handling beyond constructing `upstreamUrl`.

- [ ] **Step 2: Run the focused E2E test and verify green**

Run: `npm.cmd --prefix apps/web run test:e2e -- --grep "forwards query parameters to the Core API"`

Expected: PASS; the BFF response contains only the exact matching title.

- [ ] **Step 3: Run focused unit coverage and the complete Web unit suite**

Run: `npm.cmd --prefix apps/web run test -- --run tests/teacher-api.test.ts`

Expected: PASS; the teacher API client continues constructing BFF review URLs.

Run: `npm.cmd --prefix apps/web run test`

Expected: PASS with no test failures.

- [ ] **Step 4: Inspect the final patch**

Run: `git diff --check && git diff -- apps/web/server/api/core/[...path].ts apps/web/e2e/core-api-query-forwarding.spec.ts`

Expected: no whitespace errors; exactly one proxy behavior change plus its regression test.

- [ ] **Step 5: Commit the verified repair**

Run: `git add apps/web/server/api/core/[...path].ts apps/web/e2e/core-api-query-forwarding.spec.ts`

Run: `git commit -m "fix: forward BFF query parameters"`

### Task 3: Prepare review evidence without production mutation

**Files:**
- No source changes.

**Interfaces:**
- Consumes the green E2E and Web test outputs from Task 2.
- Produces a concise PR summary containing the observed production symptom, root cause, behavior change, and local verification evidence.

- [ ] **Step 1: Check repository state**

Run: `git status --short && git log -1 --oneline`

Expected: only the intended verified repair commit is new after the separately committed design record.

- [ ] **Step 2: Report deployment boundary**

State that production was not changed by this branch. Request separate authorization before creating a PR, merging, or deploying.
