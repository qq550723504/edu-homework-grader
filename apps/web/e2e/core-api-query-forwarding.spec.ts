import { expect, test, type APIResponse, type Page } from '@playwright/test'

const webBaseUrl = 'http://127.0.0.1:13000'
const teacherE2eToken = 'e2e-teacher-token'

interface TeacherSession {
  csrf_token: string
}

async function expectOk(response: APIResponse, operation: string): Promise<void> {
  expect(response.ok(), `${operation}: ${response.status()} ${await response.text()}`).toBe(true)
}

async function readTeacherSession(page: Page): Promise<TeacherSession> {
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': teacherE2eToken },
  })
  await expectOk(response, 'create isolated teacher E2E web session')
  const session = await page.request.get(`${webBaseUrl}/api/auth/session`)
  await expectOk(session, 'read isolated teacher E2E web session')
  return session.json() as Promise<TeacherSession>
}

async function createQuestion(page: Page, csrfToken: string, title: string): Promise<void> {
  const response = await page.request.post(`${webBaseUrl}/api/core/v1/questions`, {
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    data: {
      title,
      prompt: `What is 2 + 2? ${title}`,
      question_type: 'M1',
      policy_version: '1',
      rule: { expected: 4 },
    },
  })
  await expectOk(response, `create question ${title}`)
}

test('forwards query parameters to the Core API', async ({ page }) => {
  const session = await readTeacherSession(page)
  const marker = `BFF query ${Date.now()}`
  const matchingTitle = `${marker} match`

  await createQuestion(page, session.csrf_token, matchingTitle)
  await createQuestion(page, session.csrf_token, `${marker} other`)

  const response = await page.request.get(
    `${webBaseUrl}/api/core/v1/questions?query=${encodeURIComponent(matchingTitle)}`,
  )
  await expectOk(response, 'filter questions through the BFF')
  const payload = await response.json() as { question_versions: Array<{ title: string }> }

  expect(payload.question_versions.map((question) => question.title)).toEqual([matchingTitle])
})
