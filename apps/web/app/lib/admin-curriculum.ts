type Request = <T>(url: string, options?: {
  method?: 'POST'
  headers?: Record<string, string>
  body?: unknown
}) => Promise<T>

export type CurriculumStatus = 'draft' | 'in_review' | 'active' | 'retired'

export interface CurriculumAdminProfile {
  id: string
  code: string
  name: string
  jurisdiction: string
  version_label: string
  status: CurriculumStatus
  objective_count?: number
}

export interface CurriculumProfileDetail extends CurriculumAdminProfile {
  grade_mappings: Array<Record<string, unknown>>
  objectives: Array<Record<string, unknown>>
}

export interface CurriculumImportSummary {
  id: string
  status: CurriculumStatus
  profile_id: string
  profile: CurriculumAdminProfile
  input_format: 'json' | 'csv'
  content_digest: string
  baseline_fingerprint: string
  change_summary: string
  summary: Record<string, unknown>
  submitted_by_user_id: string
  created_at: string
  reviewed_at: string | null
  reviewed_by_user_id: string | null
  activated_at: string | null
  activated_by_user_id: string | null
}

export interface CurriculumImportIssue {
  source_path: string | null
  source_row: number | null
  source_column: string | null
  code: string
  category: string
  message: string
}

export interface CurriculumImportDetail extends CurriculumImportSummary {
  issues: CurriculumImportIssue[]
}

export interface CurriculumPageQuery {
  status?: CurriculumStatus
  limit?: number
  offset?: number
}

export interface CurriculumPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface CurriculumImportAnalysis {
  normalized_digest: string
  catalogue_fingerprint: string
  additions: string[]
  updates: string[]
  unchanged: string[]
  conflicts: CurriculumImportIssue[]
  problems: CurriculumImportIssue[]
  can_apply: boolean
}

export interface CurriculumImportSchema {
  json_schema: Record<string, unknown>
  csv_columns: string[]
}

function queryString(query: CurriculumPageQuery): string {
  const params = new URLSearchParams()
  if (query.status) params.set('status', query.status)
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  if (query.offset !== undefined) params.set('offset', String(query.offset))
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export function fetchAdminCurriculumProfiles(
  request: Request,
  query: CurriculumPageQuery = {},
): Promise<CurriculumPage<CurriculumAdminProfile>> {
  return request(`/api/core/v1/admin/curriculum/profiles${queryString(query)}`)
}

export function fetchCurriculumImports(
  request: Request,
  query: CurriculumPageQuery = {},
): Promise<CurriculumPage<CurriculumImportSummary>> {
  return request(`/api/core/v1/admin/curriculum/imports${queryString(query)}`)
}

export function fetchCurriculumImport(
  request: Request,
  batchId: string,
): Promise<CurriculumImportDetail> {
  return request(`/api/core/v1/admin/curriculum/imports/${encodeURIComponent(batchId)}`)
}

export function fetchCurriculumImportSchema(request: Request): Promise<CurriculumImportSchema> {
  return request('/api/core/v1/admin/curriculum/import-schema')
}

export function fetchCurriculumProfile(
  request: Request,
  profileCode: string,
): Promise<CurriculumProfileDetail> {
  return request(`/api/core/v1/admin/curriculum/profiles/${encodeURIComponent(profileCode)}`)
}

export function exportCurriculumProfile(
  request: Request,
  profileCode: string,
): Promise<Record<string, unknown>> {
  return request(`/api/core/v1/admin/curriculum/profiles/${encodeURIComponent(profileCode)}/export`)
}

export function fetchRetirementImpact(
  request: Request,
  profileId: string,
): Promise<Record<string, unknown>> {
  return request(`/api/core/v1/admin/curriculum/profiles/${encodeURIComponent(profileId)}/retirement-impact`)
}

function postCurriculumAction<T>(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  path: string,
  body?: Record<string, unknown>,
): Promise<T> {
  return request(path, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey },
    ...(body ? { body } : {}),
  })
}

export function submitCurriculumImportReview(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  batchId: string,
): Promise<CurriculumImportSummary> {
  return postCurriculumAction(request, csrfToken, idempotencyKey, `/api/core/v1/admin/curriculum/imports/${encodeURIComponent(batchId)}/submit-review`)
}

export function reviewCurriculumImport(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  batchId: string,
  approve: boolean,
): Promise<CurriculumImportSummary> {
  return postCurriculumAction(request, csrfToken, idempotencyKey, `/api/core/v1/admin/curriculum/imports/${encodeURIComponent(batchId)}/review`, { approve })
}

export function activateCurriculumImport(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  batchId: string,
): Promise<CurriculumImportSummary> {
  return postCurriculumAction(request, csrfToken, idempotencyKey, `/api/core/v1/admin/curriculum/imports/${encodeURIComponent(batchId)}/activate`)
}

export function retireCurriculumProfile(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  profileId: string,
): Promise<CurriculumAdminProfile> {
  return postCurriculumAction(request, csrfToken, idempotencyKey, `/api/core/v1/admin/curriculum/profiles/${encodeURIComponent(profileId)}/retire`)
}

export function dryRunCurriculumImport(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  body: Record<string, unknown>,
): Promise<CurriculumImportAnalysis> {
  return request('/api/core/v1/admin/curriculum/imports/dry-run', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey },
    body,
  })
}

export function createCurriculumImport(
  request: Request,
  csrfToken: string,
  idempotencyKey: string,
  body: Record<string, unknown>,
): Promise<CurriculumImportSummary> {
  return request('/api/core/v1/admin/curriculum/imports', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey },
    body,
  })
}
