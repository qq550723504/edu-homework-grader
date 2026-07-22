type Request = <T>(url: string, options?: {
  method?: 'POST'
  headers?: Record<string, string>
  body?: unknown
}) => Promise<T>

export const teacherAiQuestionTypes = ['M1', 'M2', 'E1', 'E2', 'E3', 'E4'] as const
export type TeacherAiQuestionType = typeof teacherAiQuestionTypes[number]

export interface CurriculumProfile {
  code: string
  name: string
  jurisdiction?: string
  version_label?: string
}

export interface CurriculumGradeMapping {
  id?: string
  internal_level: string
  external_label: string
}

export interface CurriculumObjective {
  id: string
  code: string
  subject: string
  domain?: string
  revision: {
    id: string
    text: string
    allowed_question_types: TeacherAiQuestionType[]
    difficulty_min: number
    difficulty_max: number
  }
}

export interface GenerationLimits {
  max_batch_size: number
  remaining_count: number
}

export interface CreateAiGenerationJobInput {
  curriculum_objective_revision_id: string
  question_types: TeacherAiQuestionType[]
  requested_count: number
  teacher_constraint?: string
}

export interface TeacherAiGenerationJobResult {
  id: string
}

export function expandQuestionTypeCounts(
  counts: Partial<Record<TeacherAiQuestionType, number>>,
): TeacherAiQuestionType[] {
  return teacherAiQuestionTypes.flatMap((type) => Array.from(
    { length: Math.max(0, counts[type] ?? 0) },
    () => type,
  ))
}

export async function fetchCurriculumProfiles(request: Request): Promise<CurriculumProfile[]> {
  return (await request<{ items: CurriculumProfile[] }>('/api/core/v1/curriculum-profiles')).items
}

export async function fetchCurriculumGradeMappings(
  request: Request,
  profile: string,
): Promise<CurriculumGradeMapping[]> {
  return (await request<{ items: CurriculumGradeMapping[] }>(
    `/api/core/v1/curriculum-profiles/${encodeURIComponent(profile)}/grade-mappings`,
  )).items
}

export async function fetchCurriculumObjectives(
  request: Request,
  profile: string,
  gradeLevel: string,
  subject?: string,
): Promise<CurriculumObjective[]> {
  const params = new URLSearchParams({ grade_level: gradeLevel })
  if (subject) params.set('subject', subject)
  return (await request<{ items: CurriculumObjective[] }>(
    `/api/core/v1/curriculum-profiles/${encodeURIComponent(profile)}/objectives?${params.toString()}`,
  )).items
}

export function fetchGenerationLimits(request: Request): Promise<GenerationLimits> {
  return request<GenerationLimits>('/api/core/v1/ai-question-generation/limits')
}

export function createAiGenerationJob(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  input: CreateAiGenerationJobInput,
): Promise<TeacherAiGenerationJobResult> {
  return request<TeacherAiGenerationJobResult>('/api/core/v1/ai-question-generation/jobs', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey },
    body: input,
  })
}
