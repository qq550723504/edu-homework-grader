type Request = <T>(url: string, options?: {
  method?: 'POST'
  headers?: Record<string, string>
  body?: unknown
}) => Promise<T>

export type TeacherAiQuestionType = 'M1' | 'M2' | 'E1' | 'E2' | 'E3' | 'E4'
export type TeacherAiValidationStatus = 'passed' | 'warning' | 'blocked'
export type TeacherAiRejectReason =
  | 'incorrect_answer'
  | 'out_of_scope'
  | 'unclear_wording'
  | 'duplicate'
  | 'unsuitable_for_students'
  | 'other'

export interface TeacherAiGenerationJob {
  id: string
  subject?: string | null
  status: string
  requested_count?: number
  succeeded_count?: number
  failed_count?: number
  failure_code?: string | null
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
}

export interface TeacherAiVerificationAssertions {
  final_answer_text: string
  final_answer_mathjson: string | null
  declared_max_score: number
}

export interface TeacherAiCandidate {
  objective_revision_id: string
  question_type: TeacherAiQuestionType
  policy_version: string
  prompt: string
  rule_json: Record<string, unknown>
  explanation: string
  knowledge_point: string
  difficulty: number
  verification_assertions?: TeacherAiVerificationAssertions | null
  reading_material: string | null
}

export interface TeacherAiValidationFinding {
  code: string
  severity: TeacherAiValidationStatus
  evidence: Record<string, unknown>
  remediation: string
}

export interface TeacherAiValidationRun {
  id: string
  draft_id: string
  revision_number: number
  run_number: number
  validator_version: string
  ruleset_version: string
  status: TeacherAiValidationStatus
  feature_summary: Record<string, unknown>
  findings: TeacherAiValidationFinding[]
  created_at: string
}

export interface TeacherAiDraft {
  id: string
  ordinal: number
  teacher_state: string
  candidate: TeacherAiCandidate
  revision_number: number
  validation_errors: Array<Record<string, unknown>>
}

export interface TeacherAiReviewDecision {
  draft_id: string
  action: 'accept' | 'reject'
  reason: string | null
  revision_number: number
  validation_run: TeacherAiValidationRun
  accepted_question_version_id: string | null
}

export interface TeacherAiRevisionResult {
  draft_id: string
  revision_number: number
  validation_run: TeacherAiValidationRun
}

export interface TeacherAiBatchAcceptItem {
  draft_id: string
  expected_revision_number: number
  confirm_warnings: boolean
}

export interface TeacherAiBatchAcceptResult {
  items: TeacherAiReviewDecision[]
}

export type TeacherAiCandidateEdits = Partial<{
  prompt: string
  rule_json: string | Record<string, unknown>
  explanation: string
  knowledge_point: string
  difficulty: string | number
  reading_material: string | null
}>

export async function fetchAiGenerationJobs(request: Request): Promise<TeacherAiGenerationJob[]> {
  return (await request<{ items: TeacherAiGenerationJob[] }>('/api/core/v1/ai-question-generation/jobs')).items
}

export async function fetchAiGenerationDrafts(request: Request, jobId: string): Promise<TeacherAiDraft[]> {
  return (await request<{ items: TeacherAiDraft[] }>(
    `/api/core/v1/ai-question-generation/jobs/${jobId}/questions`,
  )).items
}

export async function fetchAiValidationRuns(request: Request, draftId: string): Promise<TeacherAiValidationRun[]> {
  return (await request<{ items: TeacherAiValidationRun[] }>(
    `/api/core/v1/ai-generated-questions/${draftId}/validation-runs`,
  )).items
}

export function candidateEditInput(
  current: TeacherAiCandidate,
  edits: TeacherAiCandidateEdits,
): TeacherAiCandidate {
  const ruleJson = parseRuleJson(edits.rule_json ?? current.rule_json)
  const difficulty = parseDifficulty(edits.difficulty ?? current.difficulty)
  const readingMaterial = edits.reading_material ?? current.reading_material

  if (current.question_type === 'E4' && !readingMaterial?.trim()) {
    throw new Error('E4 candidates require reading material')
  }
  if (current.question_type !== 'E4' && readingMaterial !== null) {
    throw new Error('Only E4 candidates may include reading material')
  }

  const verificationAssertions = synchronizeVerificationAssertions(current, ruleJson)
  const rawExplanation = edits.explanation ?? current.explanation
  const explanation = verificationAssertions
    ? synchronizeExplanation(rawExplanation, verificationAssertions.final_answer_text)
    : rawExplanation

  const updated: TeacherAiCandidate = {
    ...current,
    prompt: edits.prompt ?? current.prompt,
    rule_json: ruleJson,
    explanation,
    knowledge_point: edits.knowledge_point ?? current.knowledge_point,
    difficulty,
    reading_material: readingMaterial,
    // These fields belong to the candidate already persisted on the server.
    objective_revision_id: current.objective_revision_id,
    question_type: current.question_type,
    policy_version: current.policy_version,
  }
  if (verificationAssertions !== null || current.verification_assertions !== undefined) {
    updated.verification_assertions = verificationAssertions
  }
  return updated
}

export function saveAiCandidateRevision(
  request: Request,
  csrfToken: string,
  draftId: string,
  key: string,
  expectedRevisionNumber: number,
  candidate: TeacherAiCandidate,
): Promise<TeacherAiRevisionResult> {
  return request<TeacherAiRevisionResult>(`/api/core/v1/ai-generated-questions/${draftId}/revisions`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
    body: { expected_revision_number: expectedRevisionNumber, candidate },
  })
}

export function rejectAiCandidate(
  request: Request,
  csrfToken: string,
  draftId: string,
  key: string,
  expectedRevisionNumber: number,
  reason: TeacherAiRejectReason,
  detail?: string | null,
): Promise<TeacherAiReviewDecision> {
  return request<TeacherAiReviewDecision>(`/api/core/v1/ai-generated-questions/${draftId}/reject`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
    body: { expected_revision_number: expectedRevisionNumber, reason, detail: detail ?? null },
  })
}

export function acceptAiCandidate(
  request: Request,
  csrfToken: string,
  draftId: string,
  key: string,
  expectedRevisionNumber: number,
  warningConfirmed: boolean,
): Promise<TeacherAiReviewDecision> {
  return request<TeacherAiReviewDecision>(`/api/core/v1/ai-generated-questions/${draftId}/accept`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
    body: { expected_revision_number: expectedRevisionNumber, confirm_warnings: warningConfirmed },
  })
}

export function regenerateAiCandidate(
  request: Request,
  csrfToken: string,
  draftId: string,
  key: string,
): Promise<TeacherAiGenerationJob> {
  return request<TeacherAiGenerationJob>(`/api/core/v1/ai-generated-questions/${draftId}/regenerate`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
    body: {},
  })
}

export function bulkAcceptAiCandidates(
  request: Request,
  csrfToken: string,
  jobId: string,
  key: string,
  items: TeacherAiBatchAcceptItem[],
): Promise<TeacherAiBatchAcceptResult> {
  return request<TeacherAiBatchAcceptResult>(
    `/api/core/v1/ai-question-generation/jobs/${jobId}/bulk-accept`,
    {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key },
      body: { items },
    },
  )
}

export function canAcceptCandidate(input: {
  teacher_state: string
  validation: TeacherAiValidationRun | null
  warningConfirmed: boolean
}): boolean {
  return input.teacher_state === 'pending_review'
    && input.validation !== null
    && input.validation?.status !== 'blocked'
    && (input.validation?.status !== 'warning' || input.warningConfirmed)
}

function synchronizeVerificationAssertions(
  current: TeacherAiCandidate,
  ruleJson: Record<string, unknown>,
): TeacherAiVerificationAssertions | null {
  if (current.question_type === 'M1') {
    const expected = ruleJson.expected
    if (typeof expected !== 'number' || !Number.isFinite(expected)) {
      return current.verification_assertions ?? null
    }
    return {
      final_answer_text: String(expected),
      final_answer_mathjson: null,
      declared_max_score: 1,
    }
  }

  if (current.question_type === 'M2') {
    const expected = ruleJson.expected
    if (expected === undefined) return current.verification_assertions ?? null
    const maximumScore = numericScore(ruleJson.max_score ?? 1)
    return {
      final_answer_text: displayAnswer(expected),
      final_answer_mathjson: JSON.stringify(expected),
      declared_max_score: maximumScore,
    }
  }

  return null
}

function synchronizeExplanation(explanation: string, finalAnswerText: string): string {
  const marker = 'final answer:'
  const lower = explanation.toLocaleLowerCase()
  const markerIndex = lower.lastIndexOf(marker)
  const body = (markerIndex >= 0 ? explanation.slice(0, markerIndex) : explanation).trimEnd()
  return `${body}${body ? '\n\n' : ''}Final answer: ${finalAnswerText}`
}

function displayAnswer(value: unknown): string {
  if (typeof value === 'string') return value
  const encoded = JSON.stringify(value)
  if (!encoded) throw new Error('M2 expected answer must be JSON serializable')
  return encoded
}

function numericScore(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0 || value > 100) {
    throw new Error('Maximum score must be between 0 and 100')
  }
  return value
}

function parseRuleJson(value: string | Record<string, unknown>): Record<string, unknown> {
  if (typeof value !== 'string') return value
  try {
    const parsed: unknown = JSON.parse(value)
    if (!isRecord(parsed)) throw new Error()
    return parsed
  } catch {
    throw new Error('Rule JSON must be valid JSON object')
  }
}

function parseDifficulty(value: string | number): number {
  if (typeof value === 'string' && !value.trim()) {
    throw new Error('Difficulty must be between 0 and 1')
  }
  const difficulty = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(difficulty) || difficulty < 0 || difficulty > 1) {
    throw new Error('Difficulty must be between 0 and 1')
  }
  return difficulty
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
