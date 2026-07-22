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

test('teacher creates an M1 batch and reaches its first candidate review workspace', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions/new`)

  await page.getByLabel('课程方案').selectOption({ label: 'E2E AI Generation Mathematics' })
  await page.getByLabel('年级').selectOption({ label: 'G7' })
  await page.getByLabel('学科').selectOption({ label: 'Mathematics' })
  await page.getByLabel('课程目标').selectOption({
    label: 'E2E-AI-G7-M1 · Solve Grade 7 whole-number arithmetic questions.',
  })
  await page.getByRole('button', { name: '增加 M1 题数量' }).click()

  const createResponse = page.waitForResponse(response => (
    response.request().method() === 'POST'
      && response.url().endsWith('/api/core/v1/ai-question-generation/jobs')
  ))
  await page.getByRole('button', { name: '创建生成批次' }).click()
  const createdResponse = await createResponse
  expect(createdResponse.request().postDataJSON()).toEqual({
    curriculum_objective_revision_id: expect.any(String),
    question_types: ['M1'],
    requested_count: 1,
  })
  const createdJob = await responseJson<{ id: string }>(
    createdResponse,
    'create AI generation batch through the browser',
  )

  await expect.poll(() => new URL(page.url()).searchParams.get('job')).toBe(createdJob.id)
  await expect(page).toHaveURL(/\/teacher\/ai-questions\?job=[^&]+&draft=[^&]+/)
  await expect(page.getByRole('button', { name: /候选 1/ })).toBeVisible()
})
