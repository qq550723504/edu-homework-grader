import { expect, test, type APIResponse, type Page } from '@playwright/test'

const webBaseUrl = 'http://127.0.0.1:13000'
const TEACHER_TOKEN = 'e2e-teacher-token'

async function establishTeacherSession(page: Page): Promise<void> {
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': TEACHER_TOKEN },
  })
  await expectOk(response, 'create isolated teacher E2E web session')
}

async function expectOk(response: APIResponse, operation: string): Promise<void> {
  expect(response.ok(), `${operation}: ${response.status()} ${await response.text()}`).toBe(true)
}

async function responseJson<T>(response: APIResponse, operation: string): Promise<T> {
  await expectOk(response, operation)
  return response.json() as Promise<T>
}

test('teacher edits, validates, rejects and accepts AI candidates through the browser', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions`)

  const reviewBatch = page.getByRole('button', { name: /E2E AI review batch/ })
  await expect(reviewBatch).toBeVisible()
  await reviewBatch.click()

  await expect(page).toHaveURL(/\?job=[^&]+&draft=[^&]+/)
  const selectedJobId = new URL(page.url()).searchParams.get('job')
  expect(selectedJobId).toBeTruthy()

  await expect(page.getByLabel('题目提示')).toHaveValue('E2E AI review batch M1 practice item 6.')
  await expect(page.getByText('policy_schema_invalid')).toBeVisible()
  await page.getByLabel('评分规则 JSON').fill('{"expected":6}')
  await page.getByRole('button', { name: '保存修订' }).click()
  await expect(page.getByText('候选修订已保存。')).toBeVisible()
  await expect(page.getByText('校验状态：passed')).toBeVisible()

  await page.getByLabel('拒绝原因').selectOption('duplicate')
  const rejectResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST'
      && response.url().includes('/api/core/v1/ai-generated-questions/')
      && response.url().endsWith('/reject'),
  )
  await page.getByRole('button', { name: '拒绝候选题' }).click()
  const rejectedDecision = await responseJson<{
    action: string
    reason: string | null
    accepted_question_version_id: string | null
  }>(await rejectResponsePromise, 'reject candidate through the browser')
  expect(rejectedDecision).toMatchObject({
    action: 'reject',
    reason: 'duplicate',
    accepted_question_version_id: null,
  })
  await expect(page.getByText('候选题已拒绝。')).toBeVisible()

  const rejectedDrafts = await responseJson<{ items: Array<{ ordinal: number, teacher_state: string }> }>(
    await page.request.get(
      `${webBaseUrl}/api/core/v1/ai-question-generation/jobs/${selectedJobId}/questions`,
    ),
    'read rejected candidate state',
  )
  expect(rejectedDrafts.items.find(draft => draft.ordinal === 1)?.teacher_state).toBe('rejected')

  await page.getByRole('button', { name: /候选 2/ }).click()
  const acceptResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST'
      && response.url().includes('/api/core/v1/ai-generated-questions/')
      && response.url().endsWith('/accept'),
  )
  await page.getByRole('button', { name: '接受并创建草稿' }).click()
  const acceptedDecision = await responseJson<{
    action: string
    accepted_question_version_id: string | null
  }>(await acceptResponsePromise, 'accept candidate through the browser')
  expect(acceptedDecision.action).toBe('accept')
  expect(acceptedDecision.accepted_question_version_id).toBeTruthy()
  await expect(page.getByText('候选题已接受并创建草稿。')).toBeVisible()
  await expect(page.getByTestId('accepted-notice')).toContainText('已接受')

  const questionBank = await responseJson<{
    question_versions: Array<{ id: string, status: string }>
  }>(
    await page.request.get(`${webBaseUrl}/api/core/v1/questions?query=E2E%20AI%20review%20batch`),
    'read accepted question through the teacher question bank',
  )
  const acceptedVersion = questionBank.question_versions.find(
    version => version.id === acceptedDecision.accepted_question_version_id,
  )
  expect(acceptedVersion).toMatchObject({
    id: acceptedDecision.accepted_question_version_id,
    status: 'draft',
  })
})
