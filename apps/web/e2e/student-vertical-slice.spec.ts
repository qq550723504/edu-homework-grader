import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test'

const apiBaseUrl = 'http://127.0.0.1:18000'
const webBaseUrl = 'http://127.0.0.1:13000'
const STUDENT_TOKEN = 'e2e-student-token'
const TEACHER_TOKEN = 'e2e-teacher-token'

const studentHeaders = { Authorization: `Bearer ${STUDENT_TOKEN}` }
const teacherHeaders = { Authorization: `Bearer ${TEACHER_TOKEN}` }

type AssignmentDetail = {
  attempt: { id: string }
  items: Array<{ id: string }>
}

type ReviewTask = {
  id: string
  attempt_id: string
  version: number
}

async function expectOk(response: APIResponse, operation: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${operation} failed with ${response.status()}: ${await response.text()}`)
  }
}

async function assignmentDetail(
  request: APIRequestContext,
  assignmentId: string,
): Promise<AssignmentDetail> {
  const response = await request.get(`${apiBaseUrl}/v1/student/assignments/${assignmentId}`, {
    headers: studentHeaders,
  })
  await expectOk(response, 'read student assignment')
  return response.json()
}

async function confirmAndPublish(
  request: APIRequestContext,
  assignmentId: string,
  attemptId: string,
): Promise<void> {
  const tasksResponse = await request.get(
    `${apiBaseUrl}/v1/review-tasks?assignment_id=${assignmentId}`,
    { headers: teacherHeaders },
  )
  await expectOk(tasksResponse, 'list teacher review tasks')
  const tasks = (await tasksResponse.json()) as { review_tasks: ReviewTask[] }
  const task = tasks.review_tasks.find((entry) => entry.attempt_id === attemptId)
  expect(task, `review task for attempt ${attemptId}`).toBeDefined()

  const decision = await request.post(`${apiBaseUrl}/v1/review-tasks/${task!.id}/decisions`, {
    headers: teacherHeaders,
    data: { action: 'confirm', version: task!.version },
  })
  await expectOk(decision, 'confirm review task')

  const publication = await request.post(
    `${apiBaseUrl}/v1/assignments/${assignmentId}/attempts/${attemptId}/publish-results`,
    { headers: teacherHeaders },
  )
  await expectOk(publication, 'publish attempt results')
}

async function publishCorrection(
  request: APIRequestContext,
  assignmentId: string,
  originalAttemptId: string,
): Promise<void> {
  const appeal = await request.post(
    `${apiBaseUrl}/v1/student/attempts/${originalAttemptId}/appeals`,
    {
      headers: studentHeaders,
      data: { reason: 'Please review my equivalent expression.' },
    },
  )
  await expectOk(appeal, 'create student appeal')
  const appealId = ((await appeal.json()) as { id: string }).id

  const approval = await request.post(
    `${apiBaseUrl}/v1/review-appeals/${appealId}/decisions`,
    {
      headers: teacherHeaders,
      data: { approve: true, version: 0 },
    },
  )
  await expectOk(approval, 'approve student appeal')
  const correctionAttemptId = (
    (await approval.json()) as { correction_attempt_id: string }
  ).correction_attempt_id

  const detail = await assignmentDetail(request, assignmentId)
  const saved = await request.put(
    `${apiBaseUrl}/v1/student/attempts/${correctionAttemptId}/answers/${detail.items[0].id}`,
    {
      headers: studentHeaders,
      data: {
        answer: {
          format: 'mathjson-v1',
          latex: 'x+1',
          mathjson: ['Add', 'x', 1],
        },
        version: 0,
      },
    },
  )
  await expectOk(saved, 'save correction answer')

  const submitted = await request.post(
    `${apiBaseUrl}/v1/student/attempts/${correctionAttemptId}/submit`,
    {
      headers: {
        ...studentHeaders,
        'Idempotency-Key': crypto.randomUUID(),
      },
    },
  )
  await expectOk(submitted, 'submit correction')
  await confirmAndPublish(request, assignmentId, correctionAttemptId)
}

test('student submits an algebra answer and sees published feedback and correction', async ({
  page,
  request,
}) => {
  await page.context().addCookies([
    { name: 'edu_access_token', value: STUDENT_TOKEN, url: webBaseUrl },
  ])
  await page.goto(`${webBaseUrl}/student`)

  const openAssignment = page.getByRole('link', { name: '进入作答' })
  await expect(openAssignment).toBeVisible()
  await openAssignment.click()
  await expect(page).toHaveURL(/\/student\/assignments\/[^/]+$/)

  const mathField = page.getByLabel('数学答案')
  await expect(mathField).toBeVisible()
  await mathField.fill('x+1')
  await expect(page.getByText('同步状态：已同步')).toBeVisible()

  await page.getByRole('button', { name: '提交作业' }).click()
  await expect(page.getByText('同步状态：已提交')).toBeVisible()

  const assignmentId = new URL(page.url()).pathname.split('/').at(-1)!
  const originalDetail = await assignmentDetail(request, assignmentId)
  await confirmAndPublish(request, assignmentId, originalDetail.attempt.id)

  await page.reload()
  await expect(page.getByRole('region', { name: '已发布反馈' })).toContainText(
    '表达式等价。',
  )

  await publishCorrection(request, assignmentId, originalDetail.attempt.id)
  await page.reload()
  await expect(page.getByRole('status')).toHaveText('可以查看订正结果')
})
