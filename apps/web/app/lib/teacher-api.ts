export interface TeacherClass {
  id: string
  code: string
  name: string
}

export interface TeacherQuestionVersion {
  id: string
  question_id: string
  title: string
  prompt: string
  question_type: string
  policy_version: string
  status: string
}

export interface TeacherAssignment {
  id: string
  title: string
  subject: string
  class_id: string
  class_name: string
  due_at: string
  status: string
  student_count: number
  submitted_count: number
}

export interface TeacherReviewTask {
  id: string
  assignment_id: string
  attempt_id: string
  assignment_item_id: string
  reason: string
  question_type: string
  version: number
  submitted_late: boolean
}

export interface TeacherReviewTaskDetail {
  id: string
  reason: string
  status: string
  version: number
  answer: Record<string, unknown> | null
  rule_snapshot: Record<string, unknown>
  grading: {
    decision: string
    score: number
    max_score: number
    confidence: number
    requires_review: boolean
    evidence: Record<string, unknown>
  }
  signals: Array<Record<string, unknown>>
  decisions: Array<Record<string, unknown>>
}

export interface TeacherAppeal {
  id: string
  assignment_id: string
  assignment_title: string
  attempt_id: string
  student_id: string
  student_name: string | null
  reason: string
  status: string
  version: number
  decision_reason: string | null
}

export interface CreateQuestionInput {
  title: string
  prompt: string
  question_type: string
  policy_version: string
  rule: Record<string, unknown>
}

export interface CreateTestCaseInput {
  category: string
  answer: Record<string, unknown>
  expected_decision: string
  expected_score: number
  expected_evidence: Record<string, unknown>
}

export interface QuestionTestRun {
  id: string
  status: string
  failure_summary?: string | null
  case_runs: Array<{
    category: string
    decision: string
    score: number
    evidence: Record<string, unknown>
    passed: boolean
    error_detail?: string | null
  }>
}

export interface CreateAssignmentInput {
  class_id: string
  title: string
  subject: string
  due_at: string
  submission_rule: Record<string, unknown>
}

type Request = <T>(url: string, options?: {
  method?: 'POST'
  headers?: Record<string, string>
  body?: unknown
}) => Promise<T>

export async function fetchTeacherWorkspace(request: Request): Promise<{
  classes: TeacherClass[]
  questionVersions: TeacherQuestionVersion[]
  assignments: TeacherAssignment[]
  reviewMetrics: Record<string, unknown>
  reviewTasks: TeacherReviewTask[]
}> {
  const [classes, questions, assignments, reviewMetrics, reviewTasks] = await Promise.all([
    request<{ classes: TeacherClass[] }>('/api/core/v1/classes'),
    request<{ question_versions: TeacherQuestionVersion[] }>('/api/core/v1/questions'),
    request<{ assignments: TeacherAssignment[] }>('/api/core/v1/assignments'),
    request<Record<string, unknown>>('/api/core/v1/review-metrics'),
    request<{ review_tasks: TeacherReviewTask[] }>('/api/core/v1/review-tasks'),
  ])
  return {
    classes: classes.classes,
    questionVersions: questions.question_versions,
    assignments: assignments.assignments,
    reviewMetrics,
    reviewTasks: reviewTasks.review_tasks,
  }
}

export function fetchTeacherReviewTasks(
  request: Request, filters: Record<string, string> = {},
): Promise<{ review_tasks: TeacherReviewTask[] }> {
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value),
  ).toString()
  return request(`/api/core/v1/review-tasks${query ? `?${query}` : ''}`)
}

export function fetchTeacherReviewTask(
  request: Request, taskId: string,
): Promise<TeacherReviewTaskDetail> {
  return request(`/api/core/v1/review-tasks/${taskId}`)
}

export function decideReviewTask(
  request: Request, csrfToken: string, taskId: string,
  input: { action: string; version: number; score?: number; reason?: string },
): Promise<{ id: string; action: string; final_score: number; task_version: number }> {
  return request(`/api/core/v1/review-tasks/${taskId}/decisions`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: input,
  })
}

export function batchConfirmReviewTasks(
  request: Request, csrfToken: string, assignmentId: string, taskIds: string[],
): Promise<{ decisions: Array<{ id: string; action: string }> }> {
  return request(`/api/core/v1/review-tasks/batch-confirm?assignment_id=${assignmentId}`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: { task_ids: taskIds },
  })
}

export function publishAttemptResults(
  request: Request, csrfToken: string, assignmentId: string, attemptId: string,
): Promise<{ id: string; status: string }> {
  return request(`/api/core/v1/assignments/${assignmentId}/attempts/${attemptId}/publish-results`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken },
  })
}

export function fetchTeacherAppeals(request: Request): Promise<{ appeals: TeacherAppeal[] }> {
  return request('/api/core/v1/review-appeals')
}

export function decideTeacherAppeal(
  request: Request, csrfToken: string, appealId: string,
  input: { approve: boolean; version: number; reason?: string },
): Promise<{ correction_attempt_id: string | null }> {
  return request(`/api/core/v1/review-appeals/${appealId}/decisions`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: input,
  })
}

export function createQuestion(
  request: Request,
  csrfToken: string,
  input: CreateQuestionInput,
): Promise<{ id: string; status: string }> {
  return request('/api/core/v1/questions', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken },
    body: input,
  })
}

export function createTestCase(
  request: Request,
  csrfToken: string,
  versionId: string,
  input: CreateTestCaseInput,
): Promise<{ id: string; category: string }> {
  return request(`/api/core/v1/question-versions/${versionId}/test-cases`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: input,
  })
}

export function runQuestionTests(
  request: Request, csrfToken: string, versionId: string,
): Promise<QuestionTestRun> {
  return request(`/api/core/v1/question-versions/${versionId}/test-runs`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken },
  })
}

export function publishQuestionVersion(
  request: Request, csrfToken: string, versionId: string,
): Promise<{ id: string; status: string }> {
  return request(`/api/core/v1/question-versions/${versionId}/publish`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken },
  })
}

export function createAssignment(
  request: Request, csrfToken: string, input: CreateAssignmentInput,
): Promise<{ id: string; status: string }> {
  return request('/api/core/v1/assignments', {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: input,
  })
}

export function addAssignmentItem(
  request: Request, csrfToken: string, assignmentId: string,
  input: { question_version_id: string; position: number },
): Promise<{ id: string; position: number }> {
  return request(`/api/core/v1/assignments/${assignmentId}/items`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: input,
  })
}

export function publishAssignment(
  request: Request, csrfToken: string, assignmentId: string,
): Promise<{ id: string; status: string }> {
  return request(`/api/core/v1/assignments/${assignmentId}/publish`, {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken },
  })
}
