import { expect, test, type Browser, type Page } from '@playwright/test'

const webBaseUrl = 'http://127.0.0.1:13000'
const ADMIN_A_TOKEN = 'e2e-platform-admin-a-token'
const ADMIN_B_TOKEN = 'e2e-platform-admin-b-token'

const evaluationReport = JSON.stringify({
  spec_id: 'e2e-default-governance-v1',
  exporter_version: 'e2e-export-v1',
  run_id: 'e2e-default-governance-run',
  tenant_id: 'pilot',
  watermark: '2026-07-28T00:00:00Z',
  baseline: {
    provider_name: 'fake', model_id: 'fake-v1', prompt_version: 'generator-v1', validator_version: 'verification-v1',
  },
  candidate: {
    provider_name: 'fake-candidate', model_id: 'fake-v2', prompt_version: 'generator-v1', validator_version: 'verification-v1',
  },
  promotion_eligible: true,
  export_manifest: {
    exporter_version: 'e2e-export-v1', run_id: 'e2e-default-governance-run', tenant_id: 'pilot',
    watermark: '2026-07-28T00:00:00Z', record_count: 1, issue_count: 0,
    record_digest: 'a'.repeat(64), source_counts: { accepted_directly: 1 },
  },
})

async function loggedInPage(browser: Browser, token: string): Promise<{ context: Awaited<ReturnType<Browser['newContext']>>; page: Page }> {
  const context = await browser.newContext()
  const page = await context.newPage()
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': token },
  })
  expect(response.ok(), `create E2E admin session: ${response.status()} ${await response.text()}`).toBe(true)
  return { context, page }
}

async function acceptPromptAndClick(page: Page, button: ReturnType<Page['getByRole']>, reason: string): Promise<void> {
  page.once('dialog', dialog => dialog.accept(reason))
  await button.click()
}

test('two platform administrators approve, apply, and roll back a governed default', async ({ browser }) => {
  const submitter = await loggedInPage(browser, ADMIN_A_TOKEN)
  const approver = await loggedInPage(browser, ADMIN_B_TOKEN)
  try {
    await submitter.page.goto(`${webBaseUrl}/admin`)
    await expect(submitter.page.getByText('当前默认：fake / fake-v1 / generator-v1')).toBeVisible()
    await submitter.page.getByLabel('Provider').fill('fake-candidate')
    await submitter.page.getByLabel('模型固定版本').fill('fake-v2')
    await submitter.page.getByLabel('Prompt 版本').fill('generator-v1')
    await submitter.page.getByLabel('申请说明').fill('E2E verified promotion')
    await submitter.page.getByLabel('运营评估报告 JSON').fill(evaluationReport)
    await submitter.page.getByRole('button', { name: '提交晋级申请' }).click()
    await expect(submitter.page.getByRole('status')).toHaveText('已提交晋级申请。')

    await approver.page.goto(`${webBaseUrl}/admin`)
    const candidate = approver.page.locator('li', { hasText: 'fake-v2' })
    await acceptPromptAndClick(approver.page, candidate.getByRole('button', { name: '批准' }), '独立复核通过')
    await expect(approver.page.getByText('approved：fake-v2 / generator-v1')).toBeVisible()
    await acceptPromptAndClick(approver.page, candidate.getByRole('button', { name: '应用' }), '应用候选默认值')
    await expect(approver.page.getByText('当前默认：fake-candidate / fake-v2 / generator-v1')).toBeVisible()

    const baseline = approver.page.locator('li', { hasText: 'fake-v1' })
    await acceptPromptAndClick(approver.page, baseline.getByRole('button', { name: '申请回滚' }), '候选回归')
    await expect(approver.page.locator('li', { hasText: 'fake-v1 / generator-v1：候选回归' })).toBeVisible()

    await submitter.page.reload()
    const rollback = submitter.page.locator('li', { hasText: 'fake-v1 / generator-v1：候选回归' })
    await acceptPromptAndClick(submitter.page, rollback.getByRole('button', { name: '批准' }), '独立复核回滚')
    const approvedRollback = submitter.page.locator('li', { hasText: 'approved：fake-v1 / generator-v1' })
    await acceptPromptAndClick(submitter.page, approvedRollback.getByRole('button', { name: '应用' }), '恢复基线默认值')
    await expect(submitter.page.getByText('当前默认：fake / fake-v1 / generator-v1')).toBeVisible()
  } finally {
    await Promise.all([submitter.context.close(), approver.context.close()])
  }
})
