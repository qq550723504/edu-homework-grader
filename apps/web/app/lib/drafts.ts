import Dexie, { type Table } from 'dexie'

export type SyncStatus = 'saved_locally' | 'syncing' | 'synced' | 'offline' | 'conflict'

export interface DraftRecord {
  tenantId: string
  userId: string
  attemptId: string
  itemId: string
  answer: Record<string, unknown>
  version: number
  status: SyncStatus
  updatedAt: number
  serverAnswer?: Record<string, unknown>
  serverVersion?: number
}

interface OutboxRecord extends DraftRecord {
  id: string
}

class HomeworkDraftDatabase extends Dexie {
  drafts!: Table<DraftRecord, [string, string, string, string]>
  outbox!: Table<OutboxRecord, string>

  constructor() {
    super('edu-homework-grader-drafts')
    this.version(1).stores({
      drafts: '[tenantId+userId+attemptId+itemId], attemptId, updatedAt',
      outbox: 'id, attemptId, updatedAt'
    })
  }
}

export const draftDatabase = new HomeworkDraftDatabase()

export type SaveAnswerResult =
  | { kind: 'saved'; version: number }
  | { kind: 'offline' }
  | { kind: 'conflict'; current: { answer: Record<string, unknown>; version: number } }

export interface DraftSyncApi {
  saveAnswer(record: DraftRecord): Promise<SaveAnswerResult>
}

export async function queueAnswer(input: Omit<DraftRecord, 'status' | 'updatedAt'>): Promise<void> {
  const record: DraftRecord = { ...input, status: 'saved_locally', updatedAt: Date.now() }
  const id = [input.tenantId, input.userId, input.attemptId, input.itemId].join(':')
  await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
    await draftDatabase.drafts.put(record)
    await draftDatabase.outbox.put({ ...record, id })
  })
}

export async function resetDraftDatabase(): Promise<void> {
  await draftDatabase.drafts.clear()
  await draftDatabase.outbox.clear()
}

export async function flushAttempt(attemptId: string, api: DraftSyncApi): Promise<void> {
  const records = await draftDatabase.outbox.where('attemptId').equals(attemptId).sortBy('updatedAt')
  for (const record of records) {
    const result = await api.saveAnswer(record)
    if (result.kind === 'offline') {
      await draftDatabase.drafts.update(
        [record.tenantId, record.userId, record.attemptId, record.itemId], { status: 'offline' }
      )
      return
    }
    if (result.kind === 'conflict') {
      await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
        await draftDatabase.drafts.update(
          [record.tenantId, record.userId, record.attemptId, record.itemId],
          { status: 'conflict', serverAnswer: result.current.answer, serverVersion: result.current.version }
        )
        await draftDatabase.outbox.delete(record.id)
      })
      continue
    }
    await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
      await draftDatabase.drafts.update(
        [record.tenantId, record.userId, record.attemptId, record.itemId],
        { status: 'synced', version: result.version }
      )
      await draftDatabase.outbox.delete(record.id)
    })
  }
}
