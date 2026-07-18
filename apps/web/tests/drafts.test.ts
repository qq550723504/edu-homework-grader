import { afterEach, describe, expect, it } from 'vitest'

import { draftDatabase, flushAttempt, queueAnswer, resetDraftDatabase } from '../app/lib/drafts'

afterEach(async () => {
  await resetDraftDatabase()
})

describe('assignment draft outbox', () => {
  it('persists the latest answer and coalesces later edits into one queued mutation', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { value: '5' }, version: 0
    })
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { value: '6' }, version: 0
    })

    expect(await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1']))
      .toMatchObject({ answer: { value: '6' }, status: 'saved_locally' })
    expect(await draftDatabase.outbox.count()).toBe(1)
  })

  it('keeps offline work queued and exposes a conflict without replacing the local answer', async () => {
    await queueAnswer({
      tenantId: 'tenant-1', userId: 'student-1', attemptId: 'attempt-1', itemId: 'item-1',
      answer: { value: '6' }, version: 0
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
        current: { answer: { value: '4' }, version: 2 }
      })
    })
    expect(await draftDatabase.drafts.get(['tenant-1', 'student-1', 'attempt-1', 'item-1']))
      .toMatchObject({ answer: { value: '6' }, status: 'conflict', serverAnswer: { value: '4' }, serverVersion: 2 })
  })
})
