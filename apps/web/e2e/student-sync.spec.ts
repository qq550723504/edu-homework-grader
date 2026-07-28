import { expect, test, type Page } from '@playwright/test'

const webBaseUrl = 'http://127.0.0.1:13000'
const STUDENT_TOKEN = 'e2e-student-token'
const answerSaveUrl = '**/api/core/v1/student/attempts/**/answers/**'

async function establishStudentSession(page: Page): Promise<void> {
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': STUDENT_TOKEN },
  })
  if (!response.ok()) throw new Error(`create isolated E2E web session failed: ${response.status()}`)
}

async function openTextAnswer(page: Page): Promise<void> {
  await establishStudentSession(page)
  await page.goto(`${webBaseUrl}/student`)
  const assignment = page.locator('article', {
    has: page.getByRole('heading', { name: 'Draft isolation' }),
  })
  await assignment.getByRole('link', { name: '进入作答' }).click()
  await expect(page.getByLabel('数学答案')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: '下一题' }).click()
  await expect(page.getByLabel('答案')).toBeVisible()
}

test('student can correct a 422 answer sync failure and save the next edit', async ({ page }) => {
  let saves = 0
  await page.route(answerSaveUrl, async (route) => {
    saves += 1
    if (saves === 1) {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'mathjson_invalid' } }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: 2 }),
    })
  })
  await openTextAnswer(page)

  const answer = page.getByLabel('答案')
  await answer.fill('This first answer is rejected.')
  await expect(page.getByText('同步状态：答案格式需要修改后再同步。')).toBeVisible()
  await expect(answer).toBeEnabled()

  await answer.fill('This corrected answer can be saved.')
  await expect(page.getByText('同步状态：已同步。')).toBeVisible()
  expect(saves).toBe(2)
})

test('student stops writes after a 403 answer sync failure', async ({ page }) => {
  await page.route(answerSaveUrl, async (route) => {
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'assignment_not_writable' } }),
    })
  })
  await openTextAnswer(page)

  const answer = page.getByLabel('答案')
  await answer.fill('A write that the server rejects.')
  await expect(page.getByText('同步状态：当前无法处理作答，请联系教师或管理员。')).toBeVisible()
  await expect(answer).toBeDisabled()
  await expect(page.getByRole('button', { name: '提交作业' })).toBeDisabled()
})

test('student keeps an offline answer and synchronizes it once after re-entering the page', async ({ page }) => {
  let saves = 0
  await page.route(answerSaveUrl, async (route) => {
    saves += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: 2 }),
    })
  })
  await openTextAnswer(page)

  await page.context().setOffline(true)
  const answer = page.getByLabel('答案')
  await answer.fill('This answer waits for a network connection.')
  await expect(page.getByText('同步状态：已保存到本机，等待同步')).toBeVisible()
  expect(saves).toBe(0)

  await page.goto('about:blank')
  await page.context().setOffline(false)
  await page.goto(`${webBaseUrl}/student`)
  const assignment = page.locator('article', {
    has: page.getByRole('heading', { name: 'Draft isolation' }),
  })
  await assignment.getByRole('link', { name: '进入作答' }).click()
  await page.getByRole('button', { name: '下一题' }).click()
  await expect(page.getByLabel('答案')).toHaveValue('This answer waits for a network connection.')

  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(() => saves).toBe(1)
  await expect(page.getByText('同步状态：已同步。')).toBeVisible()
})
