import { afterEach, describe, expect, it } from 'vitest'

import {
  canSubmitAttempt,
  draftDatabase,
  flushAttempt,
  getDraft,
  getSubmissionKey,
  queueAnswer,
  requeueConflictWithLocal,
  resetDraftDatabase,
  resolveConflictWithServer
} from '../app/lib/drafts'

afterEach(async () => {
  await resetDraftDatabase()
})

describe('assignment draft outbox', () => {
  it('persists the latest answer and coalesces later edits into one queued mutation', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '5' }, version: 0
    })
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '6' }, version: 0
    })

    expect(await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1']))
      .toMatchObject({ answer: { format: 'text-v1', text: '6' }, status: 'saved_locally' })
    expect(await draftDatabase.outbox.count()).toBe(1)
  })

  it('keeps offline work queued and exposes a conflict without replacing the local answer', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '6' }, version: 0
    })
    await flushAttempt('attempt-1', {
      saveAnswer: async () => ({ kind: 'offline' as const })
    })
    expect((await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1']))?.status)
      .toBe('offline')
    expect(await draftDatabase.outbox.count()).toBe(1)

    await flushAttempt('attempt-1', {
      saveAnswer: async () => ({
        kind: 'conflict' as const,
        current: { answer: { format: 'text-v1', text: '4' }, version: 2 }
      })
    })
    expect(await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1']))
      .toMatchObject({ answer: { format: 'text-v1', text: '6' }, status: 'conflict', serverAnswer: { format: 'text-v1', text: '4' }, serverVersion: 2 })
  })

  it('blocks submission until the outbox is clear and reuses one generated submission key', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '6' }, version: 0
    })
    expect(await canSubmitAttempt('attempt-1')).toBe(false)

    await flushAttempt('attempt-1', { saveAnswer: async () => ({ kind: 'saved' as const, version: 1 }) })
    expect(await canSubmitAttempt('attempt-1')).toBe(true)
    expect(await getSubmissionKey('attempt-1', () => 'key-1')).toBe('key-1')
    expect(await getSubmissionKey('attempt-1', () => 'key-2')).toBe('key-1')
  })

  it('reports the acknowledged version for the item that was synchronized', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '6' }, version: 0
    })
    const acknowledged: Array<{ itemId: string; version: number }> = []

    await flushAttempt(
      'attempt-1',
      { saveAnswer: async () => ({ kind: 'saved' as const, version: 1 }) },
      { onSaved: (record, version) => acknowledged.push({ itemId: record.itemId, version }) }
    )

    expect(acknowledged).toEqual([{ itemId: 'item-1', version: 1 }])
  })

  it('reads the latest local answer by its tenant, user, attempt, and item key', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: 'offline answer' }, version: 0
    })

    expect(await getDraft('tenant-1', 'student-1', 'attempt-1', 'item-1'))
      .toMatchObject({ answer: { format: 'text-v1', text: 'offline answer' } })
    expect(await getDraft('tenant-1', 'student-2', 'attempt-1', 'item-1')).toBeUndefined()
  })

  it.each([
    ['session_expired', { kind: 'session_expired' as const }],
    ['processing_blocked', { kind: 'processing_blocked' as const }],
    ['validation_error', { kind: 'validation_error' as const, code: 'mathjson_invalid' }]
  ])('keeps %s visible but removes it from the automatic outbox', async (status, result) => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '6' }, version: 0
    })

    await flushAttempt('attempt-1', { saveAnswer: async () => result })

    expect((await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1'])))
      .toMatchObject({ status, errorCode: status === 'validation_error' ? 'mathjson_invalid' : undefined })
    expect(await draftDatabase.outbox.count()).toBe(0)
  })

  it('keeps rate-limited work queued with a bounded retry count', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: '6' }, version: 0
    })

    await flushAttempt('attempt-1', { saveAnswer: async () => ({ kind: 'rate_limited' as const }) })

    expect((await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1'])))
      .toMatchObject({ status: 'rate_limited', retryCount: 1 })
    expect(await draftDatabase.outbox.count()).toBe(1)
  })

  it('lets the student explicitly choose the server answer or requeue the local answer after a conflict', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { format: 'text-v1', text: 'local' }, version: 0
    })
    await flushAttempt('attempt-1', {
      saveAnswer: async () => ({
        kind: 'conflict' as const,
        current: { answer: { format: 'text-v1', text: 'server' }, version: 2 }
      })
    })
    const conflict = await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1'])
    if (!conflict) throw new Error('expected conflict draft')

    await requeueConflictWithLocal(conflict)
    expect(await draftDatabase.outbox.toArray()).toMatchObject([{ version: 2, answer: { text: 'local' } }])

    await resolveConflictWithServer({ ...conflict, retryCount: 0 })
    expect(await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1']))
      .toMatchObject({ answer: { text: 'server' }, version: 2, status: 'synced' })
    expect(await draftDatabase.outbox.count()).toBe(0)
  })
})
