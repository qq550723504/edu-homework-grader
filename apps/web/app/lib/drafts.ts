import Dexie, { type Table } from 'dexie'

import type { StudentSyncOutcome } from './student-sync'

export type SyncStatus = 'saved_locally' | 'syncing' | 'synced' | 'offline' | 'conflict'
  | 'session_expired' | 'processing_blocked' | 'validation_error' | 'rate_limited' | 'server_error'

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
  errorCode?: string
  retryCount?: number
}

interface OutboxRecord extends DraftRecord {
  id: string
}

interface SubmissionRecord {
  attemptId: string
  key: string
}

class HomeworkDraftDatabase extends Dexie {
  drafts!: Table<DraftRecord, [string, string, string, string]>
  outbox!: Table<OutboxRecord, string>
  submissions!: Table<SubmissionRecord, string>

  constructor() {
    super('edu-homework-grader-drafts')
    this.version(1).stores({
      drafts: '[tenantId+userId+attemptId+itemId], attemptId, updatedAt',
      outbox: 'id, attemptId, updatedAt'
    })
    this.version(2).stores({
      drafts: '[tenantId+userId+attemptId+itemId], attemptId, updatedAt',
      outbox: 'id, attemptId, updatedAt',
      submissions: 'attemptId'
    })
  }
}

export const draftDatabase = new HomeworkDraftDatabase()

export type SaveAnswerResult = StudentSyncOutcome

export interface DraftSyncApi {
  saveAnswer(record: DraftRecord): Promise<SaveAnswerResult>
}

export interface FlushAttemptOptions {
  onSaved?(record: DraftRecord, version: number): void
}

export async function queueAnswer(input: Omit<DraftRecord, 'status' | 'updatedAt'>): Promise<void> {
  const record: DraftRecord = {
    ...input,
    status: 'saved_locally',
    updatedAt: Date.now(),
    errorCode: undefined,
    retryCount: 0,
    serverAnswer: undefined,
    serverVersion: undefined
  }
  const id = outboxId(record)
  await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
    await draftDatabase.drafts.put(record)
    await draftDatabase.outbox.put({ ...record, id })
  })
}

export async function resetDraftDatabase(): Promise<void> {
  await draftDatabase.drafts.clear()
  await draftDatabase.outbox.clear()
  await draftDatabase.submissions.clear()
}

export async function canSubmitAttempt(attemptId: string): Promise<boolean> {
  const queued = await draftDatabase.outbox.where('attemptId').equals(attemptId).count()
  const conflicts = await draftDatabase.drafts.where('attemptId').equals(attemptId)
    .filter((draft) => draft.status === 'conflict').count()
  return queued === 0 && conflicts === 0
}

export async function getSubmissionKey(
  attemptId: string,
  createKey: () => string = () => crypto.randomUUID()
): Promise<string> {
  const existing = await draftDatabase.submissions.get(attemptId)
  if (existing) return existing.key
  const key = createKey()
  await draftDatabase.submissions.put({ attemptId, key })
  return key
}

export async function flushAttempt(
  attemptId: string,
  api: DraftSyncApi,
  options: FlushAttemptOptions = {}
): Promise<void> {
  const records = await draftDatabase.outbox.where('attemptId').equals(attemptId).sortBy('updatedAt')
  for (const record of records) {
    const result = await api.saveAnswer(record)
    if (result.kind === 'offline') {
      await keepRetryableRecord(record, result)
      return
    }
    if (result.kind === 'rate_limited' || result.kind === 'server_error') {
      await keepRetryableRecord(record, result)
      return
    }
    if (result.kind === 'session_expired' || result.kind === 'processing_blocked' || result.kind === 'validation_error') {
      await stopReplayingRecord(record, result)
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
    options.onSaved?.(record, result.version)
  }
}

export async function getDraft(
  tenantId: string,
  userId: string,
  attemptId: string,
  itemId: string
): Promise<DraftRecord | undefined> {
  return draftDatabase.drafts.get([tenantId, userId, attemptId, itemId])
}

export async function resolveConflictWithServer(record: DraftRecord): Promise<void> {
  if (!record.serverAnswer || record.serverVersion === undefined) return
  const key: [string, string, string, string] = [
    record.tenantId, record.userId, record.attemptId, record.itemId
  ]
  await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
    await draftDatabase.drafts.update(key, {
      answer: record.serverAnswer,
      version: record.serverVersion,
      status: 'synced',
      serverAnswer: undefined,
      serverVersion: undefined,
      errorCode: undefined,
      retryCount: 0
    })
    await draftDatabase.outbox.delete(outboxId(record))
  })
}

export async function requeueConflictWithLocal(record: DraftRecord): Promise<void> {
  if (record.serverVersion === undefined) return
  const next: DraftRecord = {
    ...record,
    version: record.serverVersion,
    status: 'saved_locally',
    updatedAt: Date.now(),
    serverAnswer: undefined,
    serverVersion: undefined,
    errorCode: undefined,
    retryCount: 0
  }
  await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
    await draftDatabase.drafts.put(next)
    await draftDatabase.outbox.put({ ...next, id: outboxId(next) })
  })
}

function outboxId(record: Pick<DraftRecord, 'tenantId' | 'userId' | 'attemptId' | 'itemId'>): string {
  return [record.tenantId, record.userId, record.attemptId, record.itemId].join(':')
}

async function keepRetryableRecord(
  record: OutboxRecord,
  result: { kind: 'offline' | 'rate_limited' | 'server_error' }
): Promise<void> {
  const next: OutboxRecord = {
    ...record,
    status: result.kind,
    errorCode: undefined,
    retryCount: (record.retryCount ?? 0) + 1,
    updatedAt: Date.now()
  }
  await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
    await draftDatabase.drafts.put(next)
    await draftDatabase.outbox.put(next)
  })
}

async function stopReplayingRecord(
  record: OutboxRecord,
  result: { kind: 'session_expired' | 'processing_blocked' | 'validation_error'; code?: string }
): Promise<void> {
  await draftDatabase.transaction('rw', draftDatabase.drafts, draftDatabase.outbox, async () => {
    await draftDatabase.drafts.update(
      [record.tenantId, record.userId, record.attemptId, record.itemId],
      { status: result.kind, errorCode: result.kind === 'validation_error' ? result.code : undefined }
    )
    await draftDatabase.outbox.delete(record.id)
  })
}
