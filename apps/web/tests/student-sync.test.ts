import { describe, expect, it } from 'vitest'

import {
  classifyStudentSaveError,
  retryDelayMs,
  studentSyncMessage
} from '../app/lib/student-sync'

describe('student answer sync error policy', () => {
  it.each([
    [new TypeError('network failed'), 'offline'],
    [{ statusCode: 401 }, 'session_expired'],
    [{ response: { status: 403 } }, 'processing_blocked'],
    [{ statusCode: 422, data: { detail: { code: 'mathjson_invalid' } } }, 'validation_error'],
    [{ response: { status: 429, headers: { get: () => '7' } } }, 'rate_limited'],
    [{ statusCode: 503 }, 'server_error']
  ] as const)('classifies %o as %s', (error, kind) => {
    expect(classifyStudentSaveError(error)).toMatchObject({ kind })
  })

  it('keeps the public validation code but not server detail', () => {
    const outcome = classifyStudentSaveError({
      statusCode: 422,
      data: { detail: { code: 'mathjson_invalid', message: 'internal parser at https://secret.example' } }
    })

    expect(outcome).toMatchObject({ kind: 'validation_error', code: 'mathjson_invalid' })
    expect(studentSyncMessage(outcome)).toBe('答案格式需要修改后再同步。')
    expect(studentSyncMessage(outcome)).not.toContain('secret')
  })

  it('retains the server version only for an explicit conflict', () => {
    expect(classifyStudentSaveError({
      statusCode: 409,
      data: { current: { answer: { format: 'text-v1', text: 'server' }, version: 4 } }
    })).toEqual({
      kind: 'conflict',
      current: { answer: { format: 'text-v1', text: 'server' }, version: 4 }
    })
  })

  it('honors Retry-After and caps retries at three attempts', () => {
    const throttled = classifyStudentSaveError({
      response: { status: 429, headers: { get: () => '7' } }
    })

    expect(throttled).toMatchObject({ kind: 'rate_limited', retryAfterMs: 7_000 })
    expect(retryDelayMs(1, 7_000, () => 0)).toBe(7_000)
    expect(retryDelayMs(3, undefined, () => 0.5)).toBe(4_000)
    expect(retryDelayMs(4, undefined, () => 0.5)).toBeNull()
  })
})
