import { expect, test, type Browser, type Page } from '@playwright/test'
import { createHmac } from 'node:crypto'
import { E2E_EVALUATION_EVIDENCE_HMAC_KEY } from './e2e-runtime-config.mjs'

const webBaseUrl = 'http://127.0.0.1:13000'
const ADMIN_A_TOKEN = 'e2e-platform-admin-a-token'
const ADMIN_B_TOKEN = 'e2e-platform-admin-b-token'
const candidateProvider = 'openai'
const candidateModel = 'gpt-5.6-terra'
const generatorV1Fingerprint = '2c62d68956fe618bb81e72742984c8b626fbcea5645697b80929752bcfd17b5d'
const passingGate = {
  policy_id: 'e2e-default-governance-policy-v1',
  promotion_eligible: true,
  metrics: {},
  violations: [],
  rejection_reason_counts: {},
  cost_per_final_accepted_question: null,
  end_to_end_duration_ms: {},
  strata: [],
  version_summaries: [],
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

const evaluationEvidence = {
  spec_id: 'e2e-default-governance-v1',
  exporter_version: 'e2e-export-v1',
  run_id: 'e2e-default-governance-run',
  tenant_id: 'pilot',
  watermark: '2026-07-28T00:00:00Z',
  baseline: {
    provider_name: 'fake', model_id: 'fake-v1', prompt_version: 'generator-v1', prompt_template_fingerprint: generatorV1Fingerprint, validator_version: 'verification-v1',
  },
  candidate: {
    provider_name: candidateProvider, model_id: candidateModel, prompt_version: 'generator-v1', prompt_template_fingerprint: generatorV1Fingerprint, validator_version: 'verification-v1',
  },
  promotion_eligible: true,
  metric_comparisons: {},
  strata: [],
  violations: [],
  export_manifest: {
    exporter_version: 'e2e-export-v1', run_id: 'e2e-default-governance-run', tenant_id: 'pilot',
    watermark: '2026-07-28T00:00:00Z', record_count: 1, issue_count: 0,
    record_digest: 'a'.repeat(64), source_counts: { accepted_directly: 1 },
  },
  baseline_gate: passingGate,
  candidate_gate: passingGate,
}
const evaluationReport = JSON.stringify({
  report: evaluationEvidence,
  signature: createHmac('sha256', E2E_EVALUATION_EVIDENCE_HMAC_KEY)
    .update(canonicalJson(evaluationEvidence))
    .digest('hex'),
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
  test.setTimeout(60_000)
  const submitter = await loggedInPage(browser, ADMIN_A_TOKEN)
  const approver = await loggedInPage(browser, ADMIN_B_TOKEN)
  try {
    await submitter.page.goto(`${webBaseUrl}/platform`)
    await expect(submitter.page.getByText('当前默认：fake / fake-v1 / generator-v1')).toBeVisible()
    await submitter.page.getByLabel('Provider').fill(candidateProvider)
    await submitter.page.getByLabel('模型固定版本').fill(candidateModel)
    await submitter.page.getByLabel('Prompt 版本').fill('generator-v1')
    await submitter.page.getByLabel('申请说明').fill('E2E verified promotion')
    await submitter.page.getByLabel('已签名运营评估证据 JSON').fill(evaluationReport)
    await submitter.page.getByRole('button', { name: '提交晋级申请' }).click()
    await expect(submitter.page.getByRole('status')).toHaveText('已提交晋级申请。')

    await approver.page.goto(`${webBaseUrl}/platform`)
    const candidate = approver.page.locator('li', { hasText: 'E2E verified promotion' })
    await acceptPromptAndClick(approver.page, candidate.getByRole('button', { name: '批准' }), '独立复核通过')
    await expect(approver.page.getByText(`approved：${candidateProvider} / ${candidateModel} / generator-v1`)).toBeVisible()
    const approvedCandidate = approver.page.locator('li', { hasText: `approved：${candidateProvider} / ${candidateModel} / generator-v1` })
    await acceptPromptAndClick(approver.page, approvedCandidate.getByRole('button', { name: '应用' }), '应用候选默认值')
    await expect(approver.page.getByText(`当前默认：${candidateProvider} / ${candidateModel} / generator-v1`)).toBeVisible()

    const baseline = approver.page.locator('li', { hasText: 'superseded：fake / fake-v1 / generator-v1' })
    await acceptPromptAndClick(approver.page, baseline.getByRole('button', { name: '申请回滚' }), '候选回归')
    await expect(approver.page.locator('li', { hasText: 'fake / fake-v1 / generator-v1：候选回归' })).toBeVisible()

    await submitter.page.reload()
    const rollback = submitter.page.locator('li', { hasText: 'fake / fake-v1 / generator-v1：候选回归' })
    await acceptPromptAndClick(submitter.page, rollback.getByRole('button', { name: '批准' }), '独立复核回滚')
    const approvedRollback = submitter.page.locator('li', { hasText: 'approved：fake / fake-v1 / generator-v1' })
    await acceptPromptAndClick(submitter.page, approvedRollback.getByRole('button', { name: '应用' }), '恢复基线默认值')
    await expect(submitter.page.getByText('当前默认：fake / fake-v1 / generator-v1')).toBeVisible()
    const rolledBackCandidate = submitter.page.locator('li', { hasText: `rolled_back：${candidateProvider} / ${candidateModel} / generator-v1` })
    await expect(rolledBackCandidate.getByRole('button', { name: '申请回滚' })).toBeVisible()
  } finally {
    await Promise.all([submitter.context.close(), approver.context.close()])
  }
})
