export type StudentSyncFailureKind =
  | 'offline'
  | 'session_expired'
  | 'processing_blocked'
  | 'validation_error'
  | 'rate_limited'
  | 'server_error'

export type StudentSyncOutcome =
  | { kind: 'saved'; version: number }
  | { kind: 'conflict'; current: { answer: Record<string, unknown>; version: number } }
  | { kind: StudentSyncFailureKind; code?: string; retryAfterMs?: number }

interface ErrorResponse {
  status?: unknown
  headers?: unknown
  _data?: unknown
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : null
}

function responseFor(error: unknown): ErrorResponse | null {
  const value = record(error)
  const response = record(value?.response)
  if (response) return response
  return value
}

function statusFor(error: unknown): number | null {
  const value = record(error)
  const response = responseFor(error)
  const status = value?.statusCode ?? value?.status ?? response?.status
  return typeof status === 'number' ? status : null
}

function dataFor(error: unknown): Record<string, unknown> | null {
  const value = record(error)
  const response = responseFor(error)
  return record(value?.data) ?? record(response?._data)
}

function retryAfterMs(headers: unknown): number | undefined {
  const get = record(headers)?.get
  if (typeof get !== 'function') return undefined
  const raw = get.call(headers, 'Retry-After')
  const seconds = typeof raw === 'string' ? Number(raw) : Number.NaN
  return Number.isFinite(seconds) && seconds >= 0 ? seconds * 1_000 : undefined
}

function conflictCurrent(data: Record<string, unknown> | null): { answer: Record<string, unknown>; version: number } | null {
  const current = record(data?.current)
  const answer = record(current?.answer)
  const version = current?.version
  return answer && typeof version === 'number' ? { answer, version } : null
}

function publicValidationCode(data: Record<string, unknown> | null): string | undefined {
  const detail = record(data?.detail)
  return typeof detail?.code === 'string' ? detail.code : undefined
}

export function classifyStudentSaveError(error: unknown): StudentSyncOutcome {
  if (error instanceof TypeError && statusFor(error) === null) return { kind: 'offline' }

  const status = statusFor(error)
  const response = responseFor(error)
  const data = dataFor(error)
  if (status === 401) return { kind: 'session_expired' }
  if (status === 403) return { kind: 'processing_blocked' }
  if (status === 409) {
    const current = conflictCurrent(data)
    return current ? { kind: 'conflict', current } : { kind: 'processing_blocked' }
  }
  if (status === 422) return { kind: 'validation_error', code: publicValidationCode(data) }
  if (status === 429) return { kind: 'rate_limited', retryAfterMs: retryAfterMs(response?.headers) }
  if (status !== null && status >= 500) return { kind: 'server_error' }
  return { kind: 'offline' }
}

export function retryDelayMs(
  attempt: number,
  retryAfter: number | undefined,
  random: () => number = Math.random
): number | null {
  if (attempt > 3) return null
  if (retryAfter !== undefined) return retryAfter
  const base = Math.min(1_000 * 2 ** (attempt - 1), 30_000)
  return Math.round(base * (0.9 + random() * 0.2))
}

export function studentSyncMessage(outcome: StudentSyncOutcome): string {
  switch (outcome.kind) {
    case 'saved': return '已同步。'
    case 'offline': return '网络不可用，答案已保存在本机。'
    case 'session_expired': return '登录会话已过期，请重新登录。'
    case 'processing_blocked': return '当前无法处理作答，请联系教师或管理员。'
    case 'validation_error': return '答案格式需要修改后再同步。'
    case 'rate_limited': return '请求过于频繁，正在稍后重试。'
    case 'server_error': return '服务暂时不可用，正在稍后重试。'
    case 'conflict': return '答案已在其他位置更新，请选择保留的版本。'
  }
}
