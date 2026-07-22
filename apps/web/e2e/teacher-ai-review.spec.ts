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

test('teacher edits, validates, rejects and accepts AI candidates through the browser', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions`)

  const reviewBatch = page.getByRole('button', { name: /成功 2/ })
  await expect(reviewBatch).toBeVisible()
  await reviewBatch.click()

  await expect(page.getByLabel('题目提示')).toHaveValue('E2E AI review batch M1 practice item 6.')
  await expect(page.getByText('policy_schema_invalid')).toBeVisible()
  await page.getByLabel('评分规则 JSON').fill('{"expected":6}')
  await page.getByRole('button', { name: '保存修订' }).click()
  await expect(page.getByText('候选修订已保存。')).toBeVisible()
  await expect(page.getByText('校验状态：passed')).toBeVisible()

  await page.getByLabel('拒绝原因').selectOption('duplicate')
  await page.getByRole('button', { name: '拒绝候选题' }).click()
  await expect(page.getByText('候选题已拒绝。')).toBeVisible()

  await page.getByRole('button', { name: /候选 2/ }).click()
  await page.getByRole('button', { name: '接受并创建草稿' }).click()
  await expect(page.getByText('候选题已接受并创建草稿。')).toBeVisible()
  await expect(page.getByTestId('accepted-notice')).toContainText('已接受')
})
