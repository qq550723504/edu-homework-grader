# 学生答案同步治理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 让学生作答页只自动重试可恢复的保存失败，并在不扩大前端草稿功能的前提下保留离线答案。

**架构：** 现有 Dexie 只保存每题最后一次答案，以及必要的终止状态或冲突对照；HTTP 分类、退避计时器、AbortController 与页面事件监听器由当前作答页拥有。后端答案始终是权威来源，普通界面只显示一条同步状态，只有冲突或重试耗尽时出现操作。

**技术栈：** Nuxt 4、Vue 3、TypeScript、Dexie、Vitest、Playwright。

## 全局约束

- 不新增 Service Worker、后台同步器、草稿列表页面、新依赖或后端 API。
- 本地记录继续使用 tenant/user/attempt/item 组合键，不能记录访问令牌或日志中的完整答案。
- 只对网络失败、429 和 5xx 自动重试；401、403、422、409 不得进入无界循环。
- 所有新行为先写 Vitest 失败用例，再写最小实现。
- 学生可见文案使用简短中文，不暴露 HTTP 原始响应、内部 URL 或凭据。

---

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `apps/web/app/lib/student-sync.ts` | 纯函数：把 `$fetch` 失败映射为安全同步类别，计算受限重试延迟和学生可见状态。 |
| `apps/web/app/lib/drafts.ts` | 仅保存最新答案、最后同步类别、冲突服务端版本；按同步结果维护 outbox。 |
| `apps/web/app/pages/student/assignments/[assignmentId].vue` | 组装请求、重新读取会话、管理单个计时器/AbortController/监听器，并展示最少控件。 |
| `apps/web/tests/student-sync.test.ts` | 同步类别和退避纯函数测试。 |
| `apps/web/tests/drafts.test.ts` | outbox 对每种可恢复或终止结果的持久化与清理测试。 |
| `apps/web/tests/student-assignment-rendering.test.ts` | 组件处理 401/403/422/409、监听器清理和简洁 UI 的测试。 |
| `apps/web/e2e/student-sync.spec.ts` | 浏览器离线恢复、422 修改、403 阻断和重进页面的回归测试。 |

## Task 1：定义可测试的同步错误策略

**Files:**

- Create: `apps/web/app/lib/student-sync.ts`
- Test: `apps/web/tests/student-sync.test.ts`

**接口：**

```ts
export type StudentSyncFailureKind =
  | 'offline' | 'session_expired' | 'processing_blocked'
  | 'validation_error' | 'rate_limited' | 'server_error'

export type StudentSyncOutcome =
  | { kind: 'saved'; version: number }
  | { kind: 'conflict'; current: { answer: Record<string, unknown>; version: number } }
  | { kind: StudentSyncFailureKind; code?: string; retryAfterMs?: number }

export function classifyStudentSaveError(error: unknown, nowMs?: number): StudentSyncOutcome
export function retryDelayMs(attempt: number, retryAfterMs?: number, random?: () => number): number | null
export function studentSyncMessage(outcome: StudentSyncOutcome): string
```

- [ ] **Step 1：先写失败测试**

在 `student-sync.test.ts` 覆盖：无 response 的 `TypeError` 为 `offline`；401、403、422、429、503 的类别；409 带 `data.current` 的冲突；429 的秒级 `Retry-After` 转毫秒；第 1–3 次 5xx 退避有上限且加抖动；学生文案不包含服务端 detail。

```ts
expect(classifyStudentSaveError({ statusCode: 422, data: { detail: { code: 'mathjson_invalid' } } }))
  .toMatchObject({ kind: 'validation_error', code: 'mathjson_invalid' })
expect(retryDelayMs(4, undefined, () => 0.5)).toBeNull()
```

- [ ] **Step 2：运行并确认失败**

Run: `npm test -- tests/student-sync.test.ts`

Expected: FAIL，因为模块或导出尚不存在。

- [ ] **Step 3：写最小策略实现**

实现中只接受状态码、`Retry-After` 和允许的公开 `detail.code`；未知 HTTP 4xx 返回 `processing_blocked`，5xx 返回 `server_error`。`retryDelayMs` 对 429/5xx 最多三次，优先采用合法的 `Retry-After`，否则以 1 秒为基数、最大 30 秒的指数退避并叠加最多 20% 抖动；超过次数返回 `null`。

- [ ] **Step 4：运行并确认通过**

Run: `npm test -- tests/student-sync.test.ts`

Expected: PASS，所有分类与退避断言通过。

- [ ] **Step 5：提交**

```powershell
git add apps/web/app/lib/student-sync.ts apps/web/tests/student-sync.test.ts
git commit -m "feat: classify student answer sync failures"
```

## Task 2：让现有 outbox 停止无效重放

**Files:**

- Modify: `apps/web/app/lib/drafts.ts`
- Modify: `apps/web/tests/drafts.test.ts`

**接口：**

```ts
export type SyncStatus = 'saved_locally' | 'syncing' | 'synced' | 'offline'
  | 'session_expired' | 'processing_blocked' | 'validation_error'
  | 'rate_limited' | 'server_error' | 'conflict'

export interface DraftRecord { errorCode?: string; retryCount?: number; }
export async function resolveConflictWithServer(record: DraftRecord): Promise<void>
export async function requeueConflictWithLocal(record: DraftRecord): Promise<void>
```

- [ ] **Step 1：先写失败测试**

为 403、422、401 写 outbox 断言：记录保留但从 outbox 移除，状态分别为 `processing_blocked`、`validation_error`、`session_expired`。为 429/503 写三次以内保留 outbox 和递增 `retryCount` 的断言。为 409 写两项操作：采用服务端时删除 outbox 并把本地记录更新为服务端答案/版本；采用本地时以 `serverVersion` 重新入队。

```ts
await flushAttempt('attempt-1', { saveAnswer: async () => ({ kind: 'validation_error', code: 'mathjson_invalid' }) })
expect(await draftDatabase.outbox.count()).toBe(0)
expect(draft?.status).toBe('validation_error')
```

- [ ] **Step 2：运行并确认失败**

Run: `npm test -- tests/drafts.test.ts`

Expected: FAIL，因为新结果类别和冲突处理函数尚不存在。

- [ ] **Step 3：写最小持久化实现**

扩展当前 Dexie schema 时保持原有索引与已有用户数据兼容。`flushAttempt` 接收 Task 1 的 `StudentSyncOutcome`：保存成功时清 outbox；冲突保留本地与服务端副本；终止类别从 outbox 移除；可恢复类别只保留当前一条 outbox 记录与重试次数。学生下一次编辑调用 `queueAnswer` 时必须清除旧错误并重置重试次数。

- [ ] **Step 4：运行并确认通过**

Run: `npm test -- tests/drafts.test.ts`

Expected: PASS，旧有合并、离线、提交 key 测试继续通过。

- [ ] **Step 5：提交**

```powershell
git add apps/web/app/lib/drafts.ts apps/web/tests/drafts.test.ts
git commit -m "feat: stop invalid student answer replays"
```

## Task 3：在作答页组装最小状态与生命周期

**Files:**

- Modify: `apps/web/app/pages/student/assignments/[assignmentId].vue`
- Modify: `apps/web/tests/student-assignment-rendering.test.ts`

**接口：**

```ts
async function sync(): Promise<void>
async function refreshSessionAndRetry(): Promise<boolean>
function scheduleRetry(outcome: StudentSyncOutcome): void
function stopSyncWork(): void
function onOnline(): void
function onOffline(): void
function onVisibilityChange(): void
```

- [ ] **Step 1：先写失败组件测试**

在挂载辅助函数中让 `$fetch` 按 URL 和调用次数返回合成响应。覆盖：401 后成功读取 session 并只重试一次；401 再次失败时导航到 `/api/auth/login?returnTo=...` 且不清 Dexie；403 禁用编辑/提交并显示“当前无法处理作答”；422 只显示公开校验提示并在编辑后重新入队；409 只显示“采用服务器答案”和“保留我的答案”；`wrapper.unmount()` 后三个 `removeEventListener` 与 abort 被调用。

```ts
expect(wrapper.text()).toContain('答案格式需要修改后再同步')
expect(saveRequest).toHaveBeenCalledTimes(1)
await wrapper.get('[data-testid="use-server-answer"]').trigger('click')
```

- [ ] **Step 2：运行并确认失败**

Run: `npm test -- tests/student-assignment-rendering.test.ts`

Expected: FAIL，因为当前页面将这些响应全部显示为离线，且没有对应控件和卸载逻辑。

- [ ] **Step 3：写最小页面实现**

将保存请求的 catch 块替换为 `classifyStudentSaveError`。页面只维护一个 `retryTimer`、一个 `AbortController` 和一个 `sessionRefreshAttempted` 标志；创建命名事件处理器，在 `onMounted` 注册并在 `onBeforeUnmount` 调用 `stopSyncWork` 与三次 `removeEventListener`。提交与编辑控件仅在 `processing_blocked`、`session_expired` 未恢复或冲突时禁用。不要显示完整本地/服务端答案；冲突按钮只决定使用哪个已存在的记录。

- [ ] **Step 4：运行并确认通过**

Run: `npm test -- tests/student-assignment-rendering.test.ts`

Expected: PASS，页面显示安全文案，旧页面不会保留监听器或请求。

- [ ] **Step 5：提交**

```powershell
git add apps/web/app/pages/student/assignments/[assignmentId].vue apps/web/tests/student-assignment-rendering.test.ts
git commit -m "feat: govern student answer sync lifecycle"
```

## Task 4：验证真实浏览器行为

**Files:**

- Create: `apps/web/e2e/student-sync.spec.ts`
- Modify: `apps/web/e2e/student-vertical-slice.spec.ts`（仅当其已有学生登录和作答 fixture 可复用时）

- [ ] **Step 1：先写失败 Playwright 场景**

使用现有学生垂直链路的合成身份和作业，拦截答案 PUT：离线时保存后恢复网络并断言仅同步一次；422 后修改答案并断言第二次 PUT 才发生；403 后断言提交按钮禁用且没有后续 PUT；离开并重新进入页面后触发 online，断言只有一个同步请求。

```ts
await page.context().setOffline(true)
await page.getByLabel('答案').fill('synthetic answer')
await page.context().setOffline(false)
await expect.poll(() => answerPutCount).toBe(1)
```

- [ ] **Step 2：运行并确认失败**

Run: `npm run test:e2e -- student-sync.spec.ts`

Expected: FAIL，因为旧页面对 422/403 的可见状态和事件清理不符合断言。

- [ ] **Step 3：只做为通过场景所需的 fixture 调整**

若现有 E2E API 没有可控保存失败入口，只在 `e2e/student-sync.spec.ts` 以 Playwright route interception 提供 403/422/429/503 合成响应；不得修改生产 API 或写入真实答案。

- [ ] **Step 4：运行聚焦和完整前端验证**

Run: `npm run test:e2e -- student-sync.spec.ts`

Expected: PASS。

Run: `npm test; npm run build; npm run test:e2e`

Expected: PASS，既有前端测试、生产构建和浏览器链路无回归。

- [ ] **Step 5：提交**

```powershell
git add apps/web/e2e/student-sync.spec.ts apps/web/e2e/student-vertical-slice.spec.ts
git commit -m "test: cover student answer sync recovery"
```

## 计划自检

- 范围覆盖：Task 1 覆盖可解释分类和有界退避；Task 2 保证终止错误不重放且能安全处理冲突；Task 3 覆盖会话恢复、简洁 UI、监听器与请求清理；Task 4 覆盖浏览器验收。
- 非目标检查：所有任务均未增加后台同步器、草稿页面、Service Worker、后端 API 或新依赖。
- 类型一致性：`StudentSyncOutcome` 由 Task 1 产生，Task 2 的 `flushAttempt` 消费，Task 3 的请求层构造并展示，Task 4 只验证其可见行为。
