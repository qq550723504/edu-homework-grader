type Request = <T>(url: string, options?: { method?: 'POST'; headers?: Record<string, string>; body?: unknown }) => Promise<T>

export interface GenerationDefaultChange { id: string; status: string; provider_name: string; model_version: string; prompt_version: string; request_reason: string; evaluation_summary?: { promotion_eligible?: boolean; record_count?: number; issue_count?: number; candidate_gate?: { violations?: unknown[] } } }
export interface GenerationDefaultSummary { current: { provider_name: string; model_version: string; prompt_version: string } | null; pending: GenerationDefaultChange[]; history: GenerationDefaultChange[] }

export function fetchGenerationDefaults(request: Request): Promise<GenerationDefaultSummary> { return request('/api/core/v1/admin/ai-generation-defaults') }
export function submitGenerationDefaultChange(request: Request, csrfToken: string, idempotencyKey: string, body: Record<string, unknown>): Promise<GenerationDefaultChange> {
  return request('/api/core/v1/admin/ai-generation-default-change-requests', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey }, body })
}
export function decideGenerationDefaultChange(request: Request, csrfToken: string, idempotencyKey: string, id: string, action: 'approve' | 'reject' | 'apply', reason: string): Promise<GenerationDefaultChange> {
  return request('/api/core/v1/admin/ai-generation-default-change-requests/' + encodeURIComponent(id) + '/' + action, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey }, body: { reason } })
}
export function rollbackGenerationDefaultChange(request: Request, csrfToken: string, idempotencyKey: string, id: string, reason: string): Promise<GenerationDefaultChange> {
  return request('/api/core/v1/admin/ai-generation-default-change-requests/' + encodeURIComponent(id) + '/rollback', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey }, body: { reason } })
}
