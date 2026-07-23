import { expect, test, type APIResponse, type Page } from '@playwright/test'

const webBaseUrl = 'http://127.0.0.1:13000'
const TEACHER_TOKEN = 'e2e-teacher-token'

interface TeacherSession {
  csrf_token: string
}

interface TeacherAiDraft {
  id: string
  ordinal: number
  revision_number: number
  teacher_state: string
  candidate: {
    objective_revision_id: string
    question_type: string
    prompt: string
    difficulty: number
  }
}

interface TeacherAiDecision {
  draft_id: string
  action: string
  accepted_question_version_id: string | null
}

async function establishTeacherSession(page: Page): Promise<TeacherSession> {
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': TEACHER_TOKEN },
  })
  await expectOk(response, 'create isolated teacher E2E web session')
  return responseJson<TeacherSession>(
    await page.request.get(`${webBaseUrl}/api/auth/session`),
    'read teacher E2E web session',
  )
}

async function expectOk(response: APIResponse, operation: string): Promise<void> {
  expect(response.ok(), `${operation}: ${response.status()} ${await response.text()}`).toBe(true)
}

async function responseJson<T>(response: APIResponse, operation: string): Promise<T> {
  await expectOk(response, operation)
  return response.json() as Promise<T>
}

async function fetchDrafts(page: Page, jobId: string): Promise<TeacherAiDraft[]> {
  return (await responseJson<{ items: TeacherAiDraft[] }>(
    await page.request.get(
      `${webBaseUrl}/api/core/v1/ai-question-generation/jobs/${jobId}/questions`,
    ),
    `read AI generation drafts for ${jobId}`,
  )).items
}

test('teacher fixes a blocked G7 M1 and atomically accepts passed M1 plus confirmed-warning M2', async ({ page }) => {
  const teacherSession = await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions`)

  const reviewBatch = page.getByRole('button', { name: /E2E G7 M1 M2 review batch/ })
  await expect(reviewBatch).toBeVisible()
  const reviewJobTestId = await reviewBatch.getAttribute('data-testid')
  expect(reviewJobTestId).toMatch(/^generation-job-/)
  const selectedJobId = reviewJobTestId!.replace('generation-job-', '')
  await reviewBatch.click()

  await expect.poll(() => new URL(page.url()).searchParams.get('job')).toBe(selectedJobId)
  await expect(page).toHaveURL(/\?job=[^&]+&draft=[^&]+/)
  const seededDrafts = await fetchDrafts(page, selectedJobId)
  expect(seededDrafts.map(draft => draft.candidate.question_type)).toEqual(['M1', 'M2'])
  const blockedM1 = seededDrafts[0]!
  const warningM2 = seededDrafts[1]!

  await expect(page.getByLabel('题型')).toHaveValue('M1')
  await expect(page.getByText('校验状态：blocked')).toBeVisible()
  await expect(page.getByTestId('accept-candidate')).toBeDisabled()
  await expect(page.getByTestId(`batch-select-${blockedM1.id}`)).toBeDisabled()
  const blockedResponse = await page.request.post(
    `${webBaseUrl}/api/core/v1/ai-generated-questions/${blockedM1.id}/accept`,
    {
      headers: {
        'X-CSRF-Token': teacherSession.csrf_token,
        'Idempotency-Key': 'e2e-browser-blocked-accept-v1',
      },
      data: {
        expected_revision_number: blockedM1.revision_number,
        confirm_warnings: true,
      },
    },
  )
  expect(blockedResponse.status()).toBe(409)
  expect(await blockedResponse.json()).toMatchObject({
    detail: { code: 'validation_blocked' },
  })
  const blockedQuestionBank = await responseJson<{
    question_versions: Array<{ prompt: string }>
  }>(
    await page.request.get(
      `${webBaseUrl}/api/core/v1/questions?query=${encodeURIComponent(blockedM1.candidate.prompt)}`,
    ),
    'confirm blocked candidate did not create a QuestionVersion',
  )
  expect(blockedQuestionBank.question_versions.some(
    version => version.prompt === blockedM1.candidate.prompt,
  )).toBe(false)

  const saveResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST'
      && response.url().endsWith(`/api/core/v1/ai-generated-questions/${blockedM1.id}/revisions`),
  )
  await page.getByLabel('评分规则 JSON').fill('{"expected":6,"tolerance":0}')
  await page.getByTestId('save-revision').click()
  const savedRevision = await responseJson<{
    draft_id: string
    revision_number: number
    validation_run: { status: string }
  }>(await saveResponsePromise, 'repair and validate the G7 M1 candidate')
  expect(savedRevision).toMatchObject({
    draft_id: blockedM1.id,
    validation_run: { status: 'passed' },
  })
  await expect(page.getByText('候选修订已保存。')).toBeVisible()
  await expect(page.getByText('校验状态：passed')).toBeVisible()
  await page.getByTestId(`batch-select-${blockedM1.id}`).check()

  await page.getByTestId(`generation-draft-${warningM2.id}`).click()
  await expect(page.getByLabel('题型')).toHaveValue('M2')
  await expect(page.getByText('校验状态：warning')).toBeVisible()
  await page.getByTestId(`batch-select-${warningM2.id}`).check()
  await expect(page.getByTestId('bulk-accept-candidates')).toBeDisabled()
  await page.getByTestId(`batch-warning-${warningM2.id}`).check()
  await expect(page.getByTestId('bulk-accept-candidates')).toBeEnabled()

  const batchResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST'
      && response.url().endsWith(
        `/api/core/v1/ai-question-generation/jobs/${selectedJobId}/bulk-accept`,
      ),
  )
  await page.getByTestId('bulk-accept-candidates').click()
  const batchResponse = await batchResponsePromise
  expect(batchResponse.request().postDataJSON()).toEqual({
    items: [
      {
        draft_id: blockedM1.id,
        expected_revision_number: savedRevision.revision_number,
        confirm_warnings: false,
      },
      {
        draft_id: warningM2.id,
        expected_revision_number: warningM2.revision_number,
        confirm_warnings: true,
      },
    ],
  })
  const acceptedBatch = await responseJson<{ items: TeacherAiDecision[] }>(
    batchResponse,
    'atomically accept the G7 M1/M2 candidates',
  )
  expect(acceptedBatch.items).toHaveLength(2)
  expect(acceptedBatch.items.map(item => item.draft_id)).toEqual([blockedM1.id, warningM2.id])
  expect(acceptedBatch.items.every(item => (
    item.action === 'accept' && item.accepted_question_version_id !== null
  ))).toBe(true)
  await expect(page.getByText('已批量接受 2 道候选题并创建草稿。')).toBeVisible()
  await expect(page.getByTestId('accepted-notice')).toContainText('已接受')

  const questionBank = await responseJson<{
    question_versions: Array<{ id: string, question_type: string, status: string }>
  }>(
    await page.request.get(
      `${webBaseUrl}/api/core/v1/questions?query=${encodeURIComponent('E2E G7 M1 M2 review batch')}`,
    ),
    'read the atomically accepted questions through the teacher question bank',
  )
  const acceptedVersionIds = acceptedBatch.items.map(item => item.accepted_question_version_id)
  const acceptedVersions = questionBank.question_versions.filter(
    version => acceptedVersionIds.includes(version.id),
  )
  expect(acceptedVersions).toHaveLength(2)
  expect(acceptedVersions.map(version => version.question_type)).toEqual(['M1', 'M2'])
  expect(acceptedVersions.every(version => version.status === 'draft')).toBe(true)
})

test('teacher regenerates one G8 E4 candidate without mutating the ordered E1/E4 source job', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher/ai-questions/new`)

  await page.getByLabel('课程方案').selectOption({ label: 'E2E AI Generation English' })
  await page.getByLabel('年级').selectOption({ label: 'G8' })
  await page.getByLabel('学科').selectOption({ label: 'English' })
  await page.getByLabel('课程目标').selectOption({
    label: 'E2E-AI-G8-E1-E4 · Use Grade 8 English vocabulary and reading evidence.',
  })
  await page.getByTestId('question-type-E1-foundation-increment').click()
  await page.getByTestId('question-type-E4-stretch-increment').click()

  const createResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST'
      && response.url().endsWith('/api/core/v1/ai-question-generation/jobs'),
  )
  await page.getByTestId('create-ai-generation-job').click()
  const createResponse = await createResponsePromise
  expect(createResponse.request().postDataJSON()).toEqual({
    curriculum_objective_revision_id: expect.any(String),
    items: [
      { question_type: 'E1', difficulty_band: 'foundation' },
      { question_type: 'E4', difficulty_band: 'stretch' },
    ],
    requested_count: 2,
  })
  const sourceJob = await responseJson<{ id: string }>(
    createResponse,
    'create ordered G8 E1/E4 source job',
  )
  await expect.poll(() => new URL(page.url()).searchParams.get('job')).toBe(sourceJob.id)
  const sourceDraftsBefore = await fetchDrafts(page, sourceJob.id)
  expect(sourceDraftsBefore.map(draft => ({
    question_type: draft.candidate.question_type,
    difficulty: draft.candidate.difficulty,
  }))).toEqual([
    { question_type: 'E1', difficulty: 0.2 },
    { question_type: 'E4', difficulty: 0.8 },
  ])
  const sourceE4 = sourceDraftsBefore[1]!

  await page.getByTestId(`generation-draft-${sourceE4.id}`).click()
  await expect(page.getByLabel('题型')).toHaveValue('E4')
  await expect(page.getByLabel('难度')).toHaveValue('0.8')
  await expect(page.getByTestId('reading-material')).toBeVisible()

  const regenerateResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST'
      && response.url().endsWith(`/api/core/v1/ai-generated-questions/${sourceE4.id}/regenerate`),
  )
  await page.getByTestId('regenerate-candidate').click()
  const regenerateResponse = await regenerateResponsePromise
  expect(regenerateResponse.request().postDataJSON()).toEqual({})
  const regeneratedJob = await responseJson<{ id: string }>(
    regenerateResponse,
    'regenerate the selected G8 E4 candidate',
  )
  expect(regeneratedJob.id).not.toBe(sourceJob.id)
  await expect.poll(() => new URL(page.url()).searchParams.get('job')).toBe(regeneratedJob.id)
  await expect(page).toHaveURL(new RegExp(
    `/teacher/ai-questions\\?job=${regeneratedJob.id}&draft=[^&]+`,
  ))

  const regeneratedDrafts = await fetchDrafts(page, regeneratedJob.id)
  expect(regeneratedDrafts).toHaveLength(1)
  expect(regeneratedDrafts[0]?.candidate).toMatchObject({
    objective_revision_id: sourceE4.candidate.objective_revision_id,
    question_type: 'E4',
    difficulty: 0.8,
  })
  await expect(page.getByLabel('题型')).toHaveValue('E4')
  await expect(page.getByLabel('难度')).toHaveValue('0.8')
  await expect(page.getByTestId('reading-material')).toBeVisible()

  expect(await fetchDrafts(page, sourceJob.id)).toEqual(sourceDraftsBefore)
})
