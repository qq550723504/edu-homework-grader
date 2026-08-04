import { expect, test, type Browser, type Page } from '@playwright/test'

const webBaseUrl = 'http://127.0.0.1:13000'
const ADMIN_A_TOKEN = 'e2e-platform-admin-a-token'
const ADMIN_B_TOKEN = 'e2e-platform-admin-b-token'

async function loggedInPage(browser: Browser, token: string): Promise<{ context: Awaited<ReturnType<Browser['newContext']>>; page: Page }> {
  const context = await browser.newContext()
  const page = await context.newPage()
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': token },
  })
  expect(response.ok(), `create E2E admin session: ${response.status()} ${await response.text()}`).toBe(true)
  return { context, page }
}

test('two platform administrators import, review, activate, export, and retire a curriculum catalogue', async ({ browser }) => {
  test.setTimeout(90_000)
  const submitter = await loggedInPage(browser, ADMIN_A_TOKEN)
  const reviewer = await loggedInPage(browser, ADMIN_B_TOKEN)
  const suffix = Date.now().toString(36)
  const profileCode = `e2e-browser-curriculum-${suffix}`
  const profileName = `E2E Browser Curriculum ${suffix}`
  const objectiveCode = `E2E-BROWSER-${suffix.toUpperCase()}`
  const document = {
    profile: { code: profileCode, name: profileName, jurisdiction: 'e2e', version_label: '2026' },
    source: {
      issuer: 'E2E Education Board',
      title: 'Browser curriculum verification',
      canonical_url: `https://example.invalid/${profileCode}`,
      document_number: `E2E-${suffix}`,
      license: 'CC BY 4.0',
      curated_at: '2026-08-04',
    },
    grade_mappings: [{ internal_level: 'G1', external_label: 'Grade 1', position: 1 }],
    objectives: [{
      code: objectiveCode,
      grade_level: 'G1',
      subject: 'mathematics',
      domain: 'number',
      text: 'Represent small whole numbers with drawings and objects.',
      source_locator: 'browser verification section 1',
      allowed_question_types: ['M1'],
      difficulty_min: 0,
      difficulty_max: 0.3,
      activity_type: 'scored_question',
      change_summary: 'Browser verification import',
    }],
    prerequisites: [],
  }

  try {
    await submitter.page.goto(`${webBaseUrl}/platform/curriculum/import`)
    await expect(submitter.page.getByTestId('curriculum-import-ready')).toBeVisible()
    await submitter.page.getByLabel('JSON 课程目录').fill(JSON.stringify(document))
    await expect(submitter.page.getByTestId('run-curriculum-dry-run')).toBeEnabled()
    await submitter.page.getByTestId('run-curriculum-dry-run').click()
    await expect(submitter.page.getByRole('status')).toContainText('校验通过')
    await expect(submitter.page.getByText(/目录指纹/)).toBeVisible()
    await submitter.page.getByTestId('create-curriculum-draft').click()
    await expect(submitter.page).toHaveURL(/\/platform\/curriculum\/imports\//)
    await expect(submitter.page.getByText('draft')).toBeVisible()

    await submitter.page.getByTestId('submit-curriculum-review').click()
    await expect(submitter.page.getByText('in_review')).toBeVisible()

    await reviewer.page.goto(`${webBaseUrl}/platform/curriculum`)
    await reviewer.page.getByRole('link', { name: `${profileName} / 2026` }).click()
    await expect(reviewer.page).toHaveURL(/\/platform\/curriculum\/profiles\//)
    await expect(reviewer.page.getByText(objectiveCode)).toBeVisible()
    await reviewer.page.goBack()
    await reviewer.page.getByRole('link', { name: new RegExp(`${profileName} / json / in_review`) }).click()
    await expect(
      reviewer.page.getByRole('heading', { name: '拟议课程目标' }).locator('..').getByRole('listitem').filter({
        hasText: 'Represent small whole numbers with drawings and objects.',
      }),
    ).toBeVisible()
    await reviewer.page.getByTestId('approve-curriculum-import').click()
    await expect(reviewer.page.getByText('in_review')).toBeVisible()
    reviewer.page.once('dialog', dialog => dialog.dismiss())
    await reviewer.page.getByTestId('activate-curriculum-import').click()
    await expect(reviewer.page.getByText('in_review')).toBeVisible()
    reviewer.page.once('dialog', dialog => dialog.accept())
    await reviewer.page.getByTestId('activate-curriculum-import').click()
    await expect(reviewer.page.getByText('active')).toBeVisible()

    await reviewer.page.goto(`${webBaseUrl}/platform/curriculum/profiles/${profileCode}`)
    await expect(reviewer.page.getByText('active')).toBeVisible()
    await reviewer.page.getByRole('button', { name: '导出当前目录' }).click()
    await expect(reviewer.page.getByLabel('导出目录')).toContainText(objectiveCode)
    await reviewer.page.getByTestId('load-retirement-impact').click()
    await expect(reviewer.page.getByRole('heading', { name: '退休影响' })).toBeVisible()
    reviewer.page.once('dialog', dialog => dialog.accept())
    await reviewer.page.getByTestId('retire-curriculum-profile').click()
    await expect(reviewer.page.getByText('retired')).toBeVisible()
    await expect(reviewer.page.getByRole('button', { name: '导出当前目录' })).not.toBeVisible()
  } finally {
    await Promise.all([submitter.context.close(), reviewer.context.close()])
  }
})
