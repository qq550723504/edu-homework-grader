import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test'

const apiBaseUrl = 'http://127.0.0.1:18000'
const webBaseUrl = 'http://127.0.0.1:13000'
const STUDENT_TOKEN = 'e2e-student-token'
const TEACHER_TOKEN = 'e2e-teacher-token'

const studentHeaders = { Authorization: `Bearer ${STUDENT_TOKEN}` }

type AssignmentDetail = {
  attempt: { id: string }
  items: Array<{ id: string; question_version_id: string; answer?: Record<string, unknown> | null }>
}

async function expectOk(response: APIResponse, operation: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${operation} failed with ${response.status()}: ${await response.text()}`)
  }
}

async function establishStudentSession(page: import('@playwright/test').Page): Promise<void> {
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': STUDENT_TOKEN },
  })
  await expectOk(response, 'create isolated E2E web session')
}

async function establishTeacherSession(page: import('@playwright/test').Page): Promise<void> {
  const response = await page.request.post(`${webBaseUrl}/api/auth/e2e-session`, {
    headers: { 'X-E2E-Token': TEACHER_TOKEN },
  })
  await expectOk(response, 'create isolated teacher E2E web session')
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

test('student keeps text and math drafts with their own questions after switching and refreshing', async ({
  page,
  request,
}) => {
  await establishStudentSession(page)
  await page.goto(`${webBaseUrl}/student`)

  const multiQuestionAssignment = page.locator('article', {
    has: page.getByRole('heading', { name: 'Draft isolation' }),
  })
  await multiQuestionAssignment.getByRole('link', { name: '进入作答' }).click()
  const mathField = page.getByLabel('数学答案')
  await expect(mathField).toBeVisible({ timeout: 15_000 })
  await mathField.fill('x+1')
  await expect(page.getByText('同步状态：已同步')).toBeVisible()

  await page.getByRole('button', { name: '下一题' }).click()
  const textField = page.getByLabel('答案')
  await expect(textField).toBeVisible()
  await textField.fill('A concise explanation.')
  await expect(page.getByText('同步状态：已同步')).toBeVisible()

  const assignmentId = new URL(page.url()).pathname.split('/').at(-1)!
  const savedDetail = await assignmentDetail(request, assignmentId)
  expect(savedDetail.items[1].answer).toEqual({
    format: 'text-v1',
    text: 'A concise explanation.',
  })

  await page.reload()
  await expect(mathField).toHaveJSProperty('value', 'x+1')
  await page.getByRole('button', { name: '下一题' }).click()
  await expect(textField).toHaveValue('A concise explanation.')
})

test('student logout removes the protected session and no JavaScript-readable token remains', async ({ page }) => {
  const clientErrors: string[] = []
  page.on('pageerror', (error) => clientErrors.push(error.message))
  await establishStudentSession(page)
  await page.goto(`${webBaseUrl}/student`)
  await expect(page.getByRole('heading', { name: '我的作业' })).toBeVisible()
  await expect(page.getByRole('link', { name: '进入作答' }).first()).toBeVisible()

  await page.getByRole('button', { name: '退出登录' }).click()
  expect(clientErrors).toEqual([])
  await expect.poll(async () => {
    const response = await page.request.get(`${webBaseUrl}/api/auth/session`)
    const body = await response.text()
    return body ? JSON.parse(body) : null
  }).toBeNull()
  await expect(page).toHaveURL(`${webBaseUrl}/`)
  await expect(page.evaluate(() => document.cookie)).resolves.not.toContain('edu_access_token')
  await expect(page.evaluate(() => document.cookie)).resolves.not.toContain('access_token')
  await expect(page.getByRole('link', { name: '进入学生端' })).toBeVisible()
})

test('student submits, teacher reviews and publishes, then teacher approves the student appeal through browsers', async ({ browser }) => {
  test.setTimeout(60_000)
  const studentContext = await browser.newContext()
  const teacherContext = await browser.newContext()
  const studentPage = await studentContext.newPage()
  const teacherPage = await teacherContext.newPage()
  try {
    await establishStudentSession(studentPage)
    await studentPage.goto(`${webBaseUrl}/student`)
    const assignment = studentPage.locator('article', {
      has: studentPage.getByRole('heading', { name: 'Expression equivalence' }),
    })
    await assignment.getByRole('link', { name: '进入作答' }).click()
    await studentPage.getByLabel('数学答案').fill('x+1')
    await expect(studentPage.getByText('同步状态：已同步')).toBeVisible()
    await studentPage.getByRole('button', { name: '提交作业' }).click()
    await expect(studentPage.getByText('同步状态：已提交')).toBeVisible()

    await establishTeacherSession(teacherPage)
    await teacherPage.goto(`${webBaseUrl}/teacher/reviews`)
    await expect(teacherPage.getByRole('heading', { name: '复核队列' })).toBeVisible()
    await teacherPage.getByRole('button', { name: '查看证据' }).click()
    await expect(teacherPage.getByRole('heading', { name: '复核详情' })).toBeVisible()
    await teacherPage.getByRole('button', { name: '保存复核决策' }).click()
    await expect(teacherPage.getByText('复核决策已保存。')).toBeVisible()

    await teacherPage.getByRole('button', { name: '发布此学生成绩' }).click()
    await expect(teacherPage.getByText('学生成绩已发布。')).toBeVisible()

    await studentPage.reload()
    await expect(studentPage.getByRole('region', { name: '已发布反馈' })).toBeVisible()
    await studentPage.getByLabel('申诉理由').fill('Please review the equivalent expression.')
    await studentPage.getByRole('button', { name: '提交申诉' }).click()
    await expect(studentPage.getByText('申诉已提交，教师会查看评分证据后处理。')).toBeVisible()

    await teacherPage.goto(`${webBaseUrl}/teacher/appeals`)
    await expect(teacherPage.getByRole('heading', { name: '学生申诉' })).toBeVisible()
    await teacherPage.getByRole('button', { name: '处理申诉' }).click()
    await teacherPage.getByRole('button', { name: '保存申诉决定' }).click()
    await expect(teacherPage.getByText('申诉已批准，已为学生创建订正机会。')).toBeVisible()
  } finally {
    await studentContext.close()
    await teacherContext.close()
  }
})

test('teacher creates an M1 draft question through the browser', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher`)
  await page.getByRole('link', { name: '题库' }).click()
  await expect(page).toHaveURL(`${webBaseUrl}/teacher#questions`)
  await expect(page.getByRole('heading', { name: 'Expand x plus one' })).toBeVisible()

  await page.getByLabel('题目标题').fill('Browser addition')
  await page.getByLabel('题干').fill('What is 2 + 3?')
  await page.getByLabel('正确答案').fill('5')
  await page.getByRole('button', { name: '创建草稿题目' }).click()

  await expect(page.getByText('草稿题目已创建')).toBeVisible()
  const createdQuestion = page.locator('article', {
    has: page.getByRole('heading', { name: 'Browser addition' }),
  })
  await expect(createdQuestion).toContainText('draft')
})

test('teacher creates guided E1 through E4 draft questions with current policies', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher#questions`)

  const scenarios = [
    { type: 'E1', title: 'Browser E1', fill: async () => page.getByLabel('可接受答案').fill('cat') },
    { type: 'E2', title: 'Browser E2', fill: async () => {
      await page.getByLabel('词元').fill('go')
      await page.getByLabel('可接受词形').fill('went')
    } },
    { type: 'E3', title: 'Browser E3', fill: async () => page.getByRole('radio', { name: '启用语法反馈', exact: true }).check() },
    { type: 'E4', title: 'Browser E4', fill: async () => {
      await page.getByLabel('评分点名称').fill('cause')
      await page.getByLabel('证据短语').fill('bridge closed')
    } },
  ]

  for (const scenario of scenarios) {
    await page.getByLabel('题型', { exact: true }).selectOption(scenario.type)
    await page.getByLabel('题目标题').fill(scenario.title)
    await page.getByLabel('题干').fill('Answer the question.')
    await scenario.fill()
    const requestPromise = page.waitForRequest((request) => (
      request.url().endsWith('/api/core/v1/questions') && request.method() === 'POST'
    ))
    await page.getByRole('button', { name: '创建草稿题目' }).click()
    const request = await requestPromise
    if (scenario.type === 'E4') {
      expect(request.postDataJSON()).toMatchObject({ question_type: 'E4', policy_version: '2' })
    }
    await expect(page.getByText('草稿题目已创建')).toBeVisible()
  }
})

test('teacher tests and publishes an M1 question through the browser', async ({ page }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher`)
  await page.getByRole('link', { name: '题库' }).click()
  await expect(page.getByRole('heading', { name: 'Expand x plus one' })).toBeVisible()

  await page.getByLabel('题目标题').fill('Browser publishable addition')
  await page.getByLabel('题干').fill('What is 2 + 3?')
  await page.getByLabel('正确答案').fill('5')
  await page.getByRole('button', { name: '创建草稿题目' }).click()
  await expect(page.getByText('草稿题目已创建')).toBeVisible()

  const acceptedEvidence = JSON.stringify({
    max_score: 1, confidence: 1, requires_review: false,
    criteria: [{ code: 'numeric_value', passed: true, score: 1, max_score: 1 }],
    feedback: [], dependency_versions: { grader: 'e2e-m1@1' },
  })
  const rejectedEvidence = JSON.stringify({
    max_score: 1, confidence: 1, requires_review: false,
    criteria: [{ code: 'numeric_value', passed: false, score: 0, max_score: 1 }],
    feedback: [], dependency_versions: { grader: 'e2e-m1@1' },
  })
  const categories = [
    ['correct', '5', 'auto_accepted', '1', acceptedEvidence],
    ['incorrect', '4', 'auto_rejected', '0', rejectedEvidence],
    ['empty', '', 'auto_rejected', '0', rejectedEvidence],
    ['boundary', '5.0', 'auto_accepted', '1', acceptedEvidence],
  ]
  for (const [category, answer, decision, score, evidence] of categories) {
    await page.getByLabel('用例类别').fill(category)
    await page.getByLabel('学生答案 JSON').fill(JSON.stringify({ format: 'text-v1', text: answer }))
    await page.getByLabel('预期判定').fill(decision)
    await page.getByLabel('预期分数').fill(score)
    await page.getByLabel('预期证据 JSON').fill(evidence)
    await page.getByRole('button', { name: '添加测试用例' }).click()
    await expect(page.getByText('测试用例已添加')).toBeVisible()
  }

  await page.getByRole('button', { name: '运行测试' }).click()
  await expect(page.getByText('全部测试通过，可以发布。')).toBeVisible()
  await page.getByRole('button', { name: '发布题目版本' }).click()
  await expect(page.getByText('题目版本已发布')).toBeVisible()
  const publishedQuestion = page.locator('article', {
    has: page.getByRole('heading', { name: 'Browser publishable addition' }),
  })
  await expect(publishedQuestion).toContainText('published')
})

test('teacher composes an ordered mathematics assignment and student receives that order', async ({ page, request }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher`)
  await page.getByRole('navigation', { name: '教师工作区' }).getByRole('link', { name: '作业' }).click()
  await expect(page).toHaveURL(`${webBaseUrl}/teacher#assignments`)
  await expect(page.getByRole('heading', { name: '创建作业', exact: true })).toBeVisible()

  await page.getByLabel('作业标题').fill('Browser published assignment')
  await page
    .getByLabel('班级', { exact: true })
    .selectOption({ label: 'E2E-7A · E2E Year 7 A' })
  await page.getByLabel('截止时间').fill('2027-01-01T12:00')
  await page.locator('article', {
    has: page.getByRole('heading', { name: 'Expand x plus one' }),
  }).getByRole('button', { name: '添加题目 M2' }).click()
  await page.locator('article', {
    has: page.getByRole('heading', { name: 'Explain your reasoning' }),
  }).getByRole('button', { name: '添加题目 M1' }).click()
  await expect(page.getByText('共 2 题，5 分')).toBeVisible()
  await page.getByRole('button', { name: '创建作业草稿' }).click()

  await expect(page.getByText('作业草稿已创建，请确认后发布。')).toBeVisible()
  await page.getByRole('button', { name: '发布作业', exact: true }).click()
  await expect(page.getByText('作业已发布')).toBeVisible()
  const publishedAssignment = page.locator('article', {
    has: page.getByRole('heading', { name: 'Browser published assignment' }),
  })
  await expect(publishedAssignment).toContainText('published')

  const assignmentsResponse = await request.get(`${apiBaseUrl}/v1/assignments`, {
    headers: { Authorization: `Bearer ${TEACHER_TOKEN}` },
  })
  await expectOk(assignmentsResponse, 'read teacher assignments')
  const assignments = await assignmentsResponse.json() as { assignments: Array<{ id: string; title: string }> }
  const assignmentId = assignments.assignments.find((assignment) => assignment.title === 'Browser published assignment')?.id
  expect(assignmentId).toBeTruthy()
  const questionsResponse = await request.get(`${apiBaseUrl}/v1/questions`, {
    headers: { Authorization: `Bearer ${TEACHER_TOKEN}` },
  })
  await expectOk(questionsResponse, 'read teacher question versions')
  const questions = await questionsResponse.json() as { question_versions: Array<{ id: string; title: string }> }
  const expectedVersionIds = ['Expand x plus one', 'Explain your reasoning'].map((title) =>
    questions.question_versions.find((question) => question.title === title)?.id,
  )
  expect(expectedVersionIds).not.toContain(undefined)
  const detail = await assignmentDetail(request, assignmentId!)
  expect(detail.items.map((item) => item.question_version_id)).toEqual(expectedVersionIds)
})
