<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  acceptAiCandidate,
  bulkAcceptAiCandidates,
  fetchAiGenerationDrafts,
  fetchAiGenerationJobs,
  fetchAiValidationRuns,
  regenerateAiCandidate,
  rejectAiCandidate,
  saveAiCandidateRevision,
  type TeacherAiBatchAcceptItem,
  type TeacherAiCandidate,
  type TeacherAiDraft,
  type TeacherAiGenerationJob,
  type TeacherAiRejectReason,
  type TeacherAiValidationRun,
} from '../../lib/teacher-ai-review'
import { fetchCurrentPrincipal } from '../../lib/student-api'
import TeacherAiCandidateReview from './TeacherAiCandidateReview.vue'
import TeacherAiJobList from './TeacherAiJobList.vue'

const route = useRoute()
const jobs = ref<TeacherAiGenerationJob[]>([])
const drafts = ref<TeacherAiDraft[]>([])
const currentValidation = ref<TeacherAiValidationRun | null>(null)
const currentValidationKey = ref('')
const acceptedQuestionVersionIds = ref<Record<string, string>>({})
const selectedBatchDraftIds = ref<string[]>([])
const batchWarningAcknowledgements = ref<Record<string, boolean>>({})
const batchSelectionRevisions = ref<Record<string, number>>({})
const batchValidationStates = ref<Record<string, {
  revisionNumber: number
  status: TeacherAiValidationRun['status']
}>>({})
const regenerationKeys = ref<Record<string, string>>({})
const batchIdempotency = ref<{ signature: string, key: string } | null>(null)
const loading = ref(false)
const refreshing = ref(false)
const busyOperation = ref<'save' | 'reject' | 'accept' | 'bulk-accept' | 'regenerate' | null>(null)
const notice = ref('')
const errorMessage = ref('')
const syncWarning = ref('')
const pendingRefresh = ref<{
  jobId: string
  draftId: string
  idempotencyKey: string
  minimumRevisionNumber?: number
  expectedTeacherStates?: Record<string, string>
} | null>(null)
let routeLoadGeneration = 0
let selectionRefreshGeneration = 0

const selectedJobId = computed(() => queryValue(route.query.job))
const selectedDraftId = computed(() => queryValue(route.query.draft))
const selectedDraft = computed(() => drafts.value.find((draft) => draft.id === selectedDraftId.value) ?? null)
const selectedValidation = computed(() => {
  const draft = selectedDraft.value
  return draft && currentValidationKey.value === validationKey(draft)
    ? currentValidation.value
    : null
})
const selectedAcceptedQuestionVersionId = computed(() => {
  const draft = selectedDraft.value
  return draft ? acceptedQuestionVersionIds.value[validationKey(draft)] ?? null : null
})
const currentBatchSelected = computed(() => {
  const draftId = selectedDraftId.value
  return draftId !== null && selectedBatchDraftIds.value.includes(draftId)
})
const currentBatchWarningConfirmed = computed(() => {
  const draftId = selectedDraftId.value
  return draftId !== null && batchWarningAcknowledgements.value[draftId] === true
})
const currentBatchSelectable = computed(() => {
  const draft = selectedDraft.value
  const validation = selectedValidation.value
  return draft !== null
    && isPendingReview(draft)
    && validation !== null
    && validation.status !== 'blocked'
})
const batchItems = computed<TeacherAiBatchAcceptItem[]>(() => drafts.value.flatMap((draft) => {
  if (!selectedBatchDraftIds.value.includes(draft.id)
    || !isPendingReview(draft)
    || batchSelectionRevisions.value[draft.id] !== draft.revision_number) {
    return []
  }
  const validation = batchValidationStates.value[draft.id]
  if (!validation || validation.revisionNumber !== draft.revision_number || validation.status === 'blocked') {
    return []
  }
  return [{
    draft_id: draft.id,
    expected_revision_number: draft.revision_number,
    confirm_warnings: validation.status === 'warning'
      ? batchWarningAcknowledgements.value[draft.id] === true
      : false,
  }]
}))
const batchSelectionReady = computed(() => batchItems.value.length > 0
  && batchItems.value.length === selectedBatchDraftIds.value.length
  && batchItems.value.every((item) => {
    const validation = batchValidationStates.value[item.draft_id]
    return validation?.status !== 'warning' || item.confirm_warnings
  }))
const writeControlsDisabled = computed(() => loading.value
  || busyOperation.value !== null
  || refreshing.value
  || (pendingRefresh.value !== null
    && requestMatches(pendingRefresh.value.jobId, pendingRefresh.value.draftId)))

function queryValue(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

async function loadWorkspace() {
  const generation = ++routeLoadGeneration
  selectionRefreshGeneration += 1
  const requestedJobId = queryValue(route.query.job)
  const requestedDraftId = queryValue(route.query.draft)
  if (pendingRefresh.value && !requestMatches(
    pendingRefresh.value.jobId, pendingRefresh.value.draftId,
  )) {
    pendingRefresh.value = null
    syncWarning.value = ''
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const nextJobs = await fetchAiGenerationJobs($fetch)
    const jobId = nextJobs.some((job) => job.id === requestedJobId) ? requestedJobId : nextJobs[0]?.id ?? null
    const nextDrafts = jobId ? await fetchAiGenerationDrafts($fetch, jobId) : []
    if (!requestIsCurrent(generation, requestedJobId, requestedDraftId)) return

    const draftId = nextDrafts.some((draft) => draft.id === requestedDraftId)
      ? requestedDraftId
      : nextDrafts[0]?.id ?? null
    if (jobId !== requestedJobId || draftId !== requestedDraftId) {
      jobs.value = nextJobs
      drafts.value = nextDrafts
      currentValidation.value = null
      currentValidationKey.value = ''
      await navigateTo({ query: routeQuery(jobId, draftId) })
      return
    }

    const draft = nextDrafts.find((item) => item.id === draftId) ?? null
    const validation = draft ? await fetchCurrentValidation(draft) : null
    if (!requestIsCurrent(generation, requestedJobId, requestedDraftId)) return

    jobs.value = nextJobs
    drafts.value = nextDrafts
    pruneBatchIntent(nextDrafts)
    setCurrentValidation(draft, validation)
    syncWarning.value = ''
    pendingRefresh.value = null
  } catch (error: unknown) {
    if (requestIsCurrent(generation, requestedJobId, requestedDraftId)) {
      errorMessage.value = publicErrorMessage(error, '暂时无法读取 AI 出题审核数据，请稍后重试。')
    }
  } finally {
    if (generation === routeLoadGeneration) loading.value = false
  }
}

async function refreshSelection(
  jobId: string,
  draftId: string,
  minimumRevisionNumber?: number,
  expectedTeacherStates: Record<string, string> = {},
): Promise<'updated' | 'stale' | 'behind'> {
  if (!requestMatches(jobId, draftId)) return 'stale'
  const generation = ++selectionRefreshGeneration
  const owningRouteGeneration = routeLoadGeneration
  const nextDrafts = await fetchAiGenerationDrafts($fetch, jobId)
  if (!refreshIsCurrent(generation, owningRouteGeneration, jobId, draftId)) return 'stale'
  const draft = nextDrafts.find((item) => item.id === draftId) ?? null
  if (draft && minimumRevisionNumber !== undefined && draft.revision_number < minimumRevisionNumber) {
    return 'behind'
  }
  if (Object.entries(expectedTeacherStates).some(([expectedDraftId, teacherState]) => (
    nextDrafts.find(item => item.id === expectedDraftId)?.teacher_state !== teacherState
  ))) {
    return 'behind'
  }
  const validation = draft ? await fetchCurrentValidation(draft) : null
  if (!refreshIsCurrent(generation, owningRouteGeneration, jobId, draftId)) return 'stale'

  drafts.value = nextDrafts
  pruneBatchIntent(nextDrafts)
  setCurrentValidation(draft, validation)
  return 'updated'
}

async function fetchCurrentValidation(draft: TeacherAiDraft): Promise<TeacherAiValidationRun | null> {
  const runs = await fetchAiValidationRuns($fetch, draft.id)
  return runs.find((run) => run.revision_number === draft.revision_number) ?? null
}

function setCurrentValidation(draft: TeacherAiDraft | null, validation: TeacherAiValidationRun | null) {
  currentValidation.value = validation
  currentValidationKey.value = draft ? validationKey(draft) : ''
  if (!draft) return
  if (!validation) {
    removeBatchDraft(draft.id)
    return
  }
  batchValidationStates.value = {
    ...batchValidationStates.value,
    [draft.id]: {
      revisionNumber: draft.revision_number,
      status: validation.status,
    },
  }
  if (validation.status === 'blocked'
    || (selectedBatchDraftIds.value.includes(draft.id)
      && batchSelectionRevisions.value[draft.id] !== draft.revision_number)) {
    removeBatchDraft(draft.id)
  }
}

function validationKey(draft: TeacherAiDraft): string {
  return `${draft.id}:${draft.revision_number}`
}

function requestIsCurrent(generation: number, jobId: string | null, draftId: string | null): boolean {
  return generation === routeLoadGeneration
    && queryValue(route.query.job) === jobId
    && queryValue(route.query.draft) === draftId
}

function refreshIsCurrent(
  generation: number,
  owningRouteGeneration: number,
  jobId: string,
  draftId: string,
): boolean {
  return generation === selectionRefreshGeneration
    && owningRouteGeneration === routeLoadGeneration
    && requestMatches(jobId, draftId)
}

function routeQuery(jobId: string | null, draftId: string | null): Record<string, string> {
  return {
    ...(jobId ? { job: jobId } : {}),
    ...(draftId ? { draft: draftId } : {}),
  }
}

function selectJob(jobId: string) {
  return navigateTo({ query: { job: jobId } })
}

function selectDraft(draftId: string) {
  const jobId = selectedJobId.value
  if (!jobId) return
  return navigateTo({ query: { job: jobId, draft: draftId } })
}

function updateCurrentBatchSelection(event: Event) {
  const draft = selectedDraft.value
  const validation = selectedValidation.value
  const checked = event.target instanceof HTMLInputElement && event.target.checked
  if (!draft) return
  if (!checked) {
    removeBatchDraft(draft.id)
    return
  }
  if (!currentBatchSelectable.value || !validation) return
  selectedBatchDraftIds.value = [...new Set([...selectedBatchDraftIds.value, draft.id])]
  batchSelectionRevisions.value = {
    ...batchSelectionRevisions.value,
    [draft.id]: draft.revision_number,
  }
  batchValidationStates.value = {
    ...batchValidationStates.value,
    [draft.id]: {
      revisionNumber: draft.revision_number,
      status: validation.status,
    },
  }
  if (validation.status === 'warning') {
    batchWarningAcknowledgements.value = {
      ...batchWarningAcknowledgements.value,
      [draft.id]: false,
    }
  }
}

function updateCurrentBatchWarning(event: Event) {
  const draft = selectedDraft.value
  const checked = event.target instanceof HTMLInputElement && event.target.checked
  if (!draft
    || !selectedBatchDraftIds.value.includes(draft.id)
    || selectedValidation.value?.status !== 'warning') {
    return
  }
  batchWarningAcknowledgements.value = {
    ...batchWarningAcknowledgements.value,
    [draft.id]: checked,
  }
}

function removeBatchDraft(draftId: string) {
  selectedBatchDraftIds.value = selectedBatchDraftIds.value.filter(id => id !== draftId)
  batchWarningAcknowledgements.value = omitKey(batchWarningAcknowledgements.value, draftId)
  batchSelectionRevisions.value = omitKey(batchSelectionRevisions.value, draftId)
}

function pruneBatchIntent(nextDrafts: TeacherAiDraft[]) {
  const nextDraftsById = new Map(nextDrafts.map(draft => [draft.id, draft]))
  for (const draftId of selectedBatchDraftIds.value) {
    const draft = nextDraftsById.get(draftId)
    if (!draft
      || !isPendingReview(draft)
      || batchSelectionRevisions.value[draftId] !== draft.revision_number) {
      removeBatchDraft(draftId)
    }
  }
}

function resetBatchIntent() {
  selectedBatchDraftIds.value = []
  batchWarningAcknowledgements.value = {}
  batchSelectionRevisions.value = {}
  batchValidationStates.value = {}
  batchIdempotency.value = null
}

function omitKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([entryKey]) => entryKey !== key))
}

async function csrfToken(): Promise<string> {
  const principal = await fetchCurrentPrincipal($fetch)
  if (!principal.csrf_token) throw new MissingCsrfTokenError()
  return principal.csrf_token
}

async function saveRevision(candidate: TeacherAiCandidate) {
  const draft = selectedDraft.value
  const jobId = selectedJobId.value
  if (!jobId || !draft || !isPendingReview(draft) || writeControlsDisabled.value) return
  await runWrite('save', jobId, draft, async (csrf, key) => {
    const result = await saveAiCandidateRevision(
      $fetch, csrf, draft.id, key, draft.revision_number, candidate,
    )
    return {
      message: '候选修订已保存。',
      validation: result.validation_run,
      draftPatch: { candidate, revision_number: result.revision_number },
    }
  })
}

async function rejectCandidate(reason: TeacherAiRejectReason, detail: string) {
  const draft = selectedDraft.value
  const jobId = selectedJobId.value
  if (!jobId || !draft || !isPendingReview(draft) || writeControlsDisabled.value) return
  await runWrite('reject', jobId, draft, async (csrf, key) => {
    const result = await rejectAiCandidate(
      $fetch, csrf, draft.id, key, draft.revision_number, reason, detail,
    )
    return {
      message: '候选题已拒绝。',
      validation: result.validation_run,
      draftPatch: { teacher_state: 'rejected' },
    }
  })
}

async function acceptCandidate(input: { confirmWarnings: boolean }) {
  const draft = selectedDraft.value
  const jobId = selectedJobId.value
  if (!jobId || !draft || !isPendingReview(draft) || writeControlsDisabled.value) return
  await runWrite('accept', jobId, draft, async (csrf, key) => {
    const result = await acceptAiCandidate(
      $fetch, csrf, draft.id, key, draft.revision_number, input.confirmWarnings,
    )
    return {
      message: '候选题已接受并创建草稿。',
      validation: result.validation_run,
      acceptedQuestionVersionId: result.accepted_question_version_id,
      draftPatch: { teacher_state: 'accepted' },
    }
  })
}

async function acceptBatch() {
  const jobId = selectedJobId.value
  const draft = selectedDraft.value
  const items = batchItems.value
  if (!jobId || !draft || !batchSelectionReady.value || writeControlsDisabled.value) return
  const idempotencyKey = batchIdempotencyKey(items)
  busyOperation.value = 'bulk-accept'
  notice.value = ''
  errorMessage.value = ''
  syncWarning.value = ''
  try {
    const csrf = await csrfToken()
    const result = await bulkAcceptAiCandidates($fetch, csrf, jobId, idempotencyKey, items)
    if (selectedJobId.value !== jobId) return
    const expectedTeacherStates: Record<string, string> = {}
    for (const decision of result.items) {
      const currentDraft = drafts.value.find(item => item.id === decision.draft_id)
      if (!currentDraft || decision.action !== 'accept') continue
      const updatedDraft = applyWritePatch(currentDraft, {
        teacher_state: 'accepted',
        revision_number: decision.revision_number,
      })
      expectedTeacherStates[decision.draft_id] = 'accepted'
      batchValidationStates.value = {
        ...batchValidationStates.value,
        [decision.draft_id]: {
          revisionNumber: decision.revision_number,
          status: decision.validation_run.status,
        },
      }
      if (selectedDraftId.value === decision.draft_id) {
        setCurrentValidation(updatedDraft, decision.validation_run)
      }
      if (decision.accepted_question_version_id) {
        acceptedQuestionVersionIds.value = {
          ...acceptedQuestionVersionIds.value,
          [validationKey(updatedDraft)]: decision.accepted_question_version_id,
        }
      }
      removeBatchDraft(decision.draft_id)
    }
    notice.value = `已批量接受 ${result.items.length} 道候选题并创建草稿。`
    try {
      const refresh = await refreshSelection(jobId, draft.id, undefined, expectedTeacherStates)
      if (refresh === 'updated') pendingRefresh.value = null
      if (refresh === 'behind') {
        deferRefresh(jobId, draft.id, idempotencyKey, undefined, expectedTeacherStates)
      }
    } catch {
      if (selectedJobId.value === jobId) {
        deferRefresh(jobId, draft.id, idempotencyKey, undefined, expectedTeacherStates)
      }
    }
  } catch (error: unknown) {
    if (selectedJobId.value !== jobId) return
    errorMessage.value = publicErrorMessage(
      error, '暂时无法批量接受 AI 候选题，请稍后重试。',
    )
  } finally {
    busyOperation.value = null
  }
}

function batchIdempotencyKey(items: TeacherAiBatchAcceptItem[]): string {
  const signature = JSON.stringify(items)
  if (batchIdempotency.value?.signature === signature) return batchIdempotency.value.key
  const key = crypto.randomUUID()
  batchIdempotency.value = { signature, key }
  return key
}

async function regenerateCandidate() {
  const jobId = selectedJobId.value
  const draft = selectedDraft.value
  if (!jobId || !draft || !isPendingReview(draft) || writeControlsDisabled.value) return
  busyOperation.value = 'regenerate'
  notice.value = ''
  errorMessage.value = ''
  syncWarning.value = ''
  const idempotencyKey = regenerationKeys.value[draft.id] ?? crypto.randomUUID()
  regenerationKeys.value = {
    ...regenerationKeys.value,
    [draft.id]: idempotencyKey,
  }
  try {
    const csrf = await csrfToken()
    const regeneratedJob = await regenerateAiCandidate(
      $fetch, csrf, draft.id, idempotencyKey,
    )
    if (!requestMatches(jobId, draft.id)) return
    await navigateTo({ query: { job: regeneratedJob.id } })
  } catch (error: unknown) {
    if (!requestMatches(jobId, draft.id)) return
    errorMessage.value = publicErrorMessage(
      error, '暂时无法重新生成 AI 候选题，请稍后重试。',
    )
  } finally {
    busyOperation.value = null
  }
}

function isPendingReview(draft: TeacherAiDraft): boolean {
  return draft.teacher_state === 'pending_review'
}

async function runWrite(
  operation: 'save' | 'reject' | 'accept',
  jobId: string,
  draft: TeacherAiDraft,
  write: (csrf: string, key: string) => Promise<{
    message: string
    validation: TeacherAiValidationRun
    acceptedQuestionVersionId?: string | null
    draftPatch?: Partial<Pick<TeacherAiDraft, 'candidate' | 'revision_number' | 'teacher_state'>>
  }>,
) {
  busyOperation.value = operation
  notice.value = ''
  errorMessage.value = ''
  syncWarning.value = ''
  const idempotencyKey = crypto.randomUUID()
  try {
    const csrf = await csrfToken()
    const result = await write(csrf, idempotencyKey)
    if (!requestMatches(jobId, draft.id)) return
    const updatedDraft = applyWritePatch(draft, result.draftPatch)
    notice.value = result.message
    currentValidation.value = result.validation
    currentValidationKey.value = validationKey(updatedDraft)
    if (result.acceptedQuestionVersionId) {
      acceptedQuestionVersionIds.value = {
        ...acceptedQuestionVersionIds.value,
        [validationKey(updatedDraft)]: result.acceptedQuestionVersionId,
      }
    }
    const expectedTeacherStates = result.draftPatch?.teacher_state
      ? { [draft.id]: result.draftPatch.teacher_state }
      : {}
    try {
      const refresh = await refreshSelection(
        jobId,
        draft.id,
        result.validation.revision_number,
        expectedTeacherStates,
      )
      if (refresh === 'updated') pendingRefresh.value = null
      if (refresh === 'behind') {
        deferRefresh(
          jobId,
          draft.id,
          idempotencyKey,
          result.validation.revision_number,
          expectedTeacherStates,
        )
      }
    } catch {
      if (requestMatches(jobId, draft.id)) {
        deferRefresh(
          jobId,
          draft.id,
          idempotencyKey,
          result.validation.revision_number,
          expectedTeacherStates,
        )
      }
    }
  } catch (error: unknown) {
    if (!requestMatches(jobId, draft.id)) return
    if (isRevisionConflict(error)) {
      try {
        const refresh = await refreshSelection(jobId, draft.id)
        if (refresh === 'updated') notice.value = '候选已被更新，已加载最新修订。'
      } catch (reloadError: unknown) {
        errorMessage.value = publicErrorMessage(
          reloadError, '暂时无法读取最新候选修订，请稍后重试。',
        )
      }
    } else {
      errorMessage.value = publicErrorMessage(
        error, '暂时无法完成 AI 出题审核操作，请稍后重试。',
      )
    }
  } finally {
    busyOperation.value = null
  }
}

function applyWritePatch(
  draft: TeacherAiDraft,
  patch: Partial<Pick<TeacherAiDraft, 'candidate' | 'revision_number' | 'teacher_state'>> | undefined,
): TeacherAiDraft {
  if (!patch) return draft
  const updatedDraft = { ...draft, ...patch }
  drafts.value = drafts.value.map((item) => item.id === draft.id ? updatedDraft : item)
  if (!isPendingReview(updatedDraft)
    || (selectedBatchDraftIds.value.includes(updatedDraft.id)
      && batchSelectionRevisions.value[updatedDraft.id] !== updatedDraft.revision_number)) {
    removeBatchDraft(updatedDraft.id)
  }
  return updatedDraft
}

function deferRefresh(
  jobId: string,
  draftId: string,
  idempotencyKey: string,
  minimumRevisionNumber?: number,
  expectedTeacherStates?: Record<string, string>,
) {
  pendingRefresh.value = {
    jobId,
    draftId,
    idempotencyKey,
    minimumRevisionNumber,
    expectedTeacherStates,
  }
  syncWarning.value = '操作已成功，但最新审核状态暂时无法刷新。请重试刷新。'
}

async function retryRefresh() {
  const pending = pendingRefresh.value
  if (!pending || !requestMatches(pending.jobId, pending.draftId)) return
  const operationIdentity = pending.idempotencyKey
  refreshing.value = true
  try {
    const refresh = await refreshSelection(
      pending.jobId,
      pending.draftId,
      pending.minimumRevisionNumber,
      pending.expectedTeacherStates,
    )
    if (refresh === 'updated' && pendingRefresh.value?.idempotencyKey === operationIdentity) {
      pendingRefresh.value = null
      syncWarning.value = ''
    }
  } catch {
    if (pendingRefresh.value?.idempotencyKey === operationIdentity) {
      syncWarning.value = '操作已成功，但最新审核状态暂时无法刷新。请重试刷新。'
    }
  } finally {
    refreshing.value = false
  }
}

function requestMatches(jobId: string, draftId: string): boolean {
  return selectedJobId.value === jobId && selectedDraftId.value === draftId
}

function isRevisionConflict(error: unknown): boolean {
  return errorCode(error) === 'review_revision_conflict'
}

function publicErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof MissingCsrfTokenError) return '登录会话已过期，请重新登录。'
  if (errorCode(error) === 'rejection_detail_required') return '选择“其他”时，请填写拒绝详情。'
  const status = errorStatus(error)
  if (status === 401 || status === 403) return '登录会话已过期，请重新登录。'
  if (status === 404) return '未找到所选的 AI 出题批次或候选题。'
  if (status === 429) return '请求过于频繁，请稍后重试。'
  if (status === 503) return 'AI 出题审核服务暂时不可用，请稍后重试。'
  if (status === 409) return '候选题状态已变更，请刷新后重试。'
  if (status === 422) return '提交内容不符合要求，请检查后重试。'
  if (error instanceof TypeError) return '网络连接异常，请检查网络后重试。'
  return fallback
}

function errorCode(error: unknown): string | null {
  if (!isRecord(error) || !isRecord(error.data) || !isRecord(error.data.detail)) return null
  return typeof error.data.detail.code === 'string' ? error.data.detail.code : null
}

function errorStatus(error: unknown): number | null {
  if (!isRecord(error)) return null
  const response = isRecord(error.response) ? error.response : null
  const data = isRecord(error.data) ? error.data : null
  const status = error.statusCode ?? error.status ?? response?.status ?? data?.statusCode ?? data?.status
  return typeof status === 'number' ? status : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

class MissingCsrfTokenError extends Error {}

onMounted(loadWorkspace)
watch(() => route.query, loadWorkspace)
watch(selectedJobId, (jobId, previousJobId) => {
  if (jobId !== previousJobId) resetBatchIntent()
})
</script>

<template>
  <section class="ai-review-workspace" aria-labelledby="ai-review-workspace-heading">
    <header class="teacher-page-heading">
      <div>
        <p class="eyebrow">教师端 · AI 出题</p>
        <h1 id="ai-review-workspace-heading">AI 出题审核</h1>
        <p class="teacher-page-heading__copy">查看生成批次，修订候选题并完成接受或拒绝决策。</p>
      </div>
      <NuxtLink class="button primary" to="/teacher/ai-questions/new">生成新批次</NuxtLink>
    </header>

    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="errorMessage" class="notice" role="alert">{{ errorMessage }}</p>
    <p v-if="syncWarning" class="notice" role="alert">
      {{ syncWarning }}
      <button :disabled="refreshing" data-testid="retry-refresh" type="button" @click="retryRefresh">重试刷新</button>
    </p>
    <p v-if="loading" class="notice" role="status">正在加载 AI 出题审核数据…</p>

    <div class="ai-review-workspace__grid">
      <aside class="card" aria-label="AI 出题审核选择器">
        <TeacherAiJobList
          :jobs="jobs"
          :selected-job-id="selectedJobId"
          @select-job="selectJob"
        />
        <section v-if="selectedJobId" aria-label="候选题列表">
          <h2>候选题</h2>
          <ul>
            <li v-for="draft in drafts" :key="draft.id">
              <button
                :aria-current="selectedDraftId === draft.id ? 'true' : undefined"
                :data-testid="`generation-draft-${draft.id}`"
                type="button"
                @click="selectDraft(draft.id)"
              >
                候选 {{ draft.ordinal }} · 修订 {{ draft.revision_number }}
              </button>
            </li>
          </ul>
          <p v-if="!loading && drafts.length === 0">该批次暂无候选题。</p>
        </section>
      </aside>

      <section class="card wide ai-review-workspace__review" aria-live="polite">
        <section v-if="selectedDraft" class="batch-review-controls" aria-label="批量接受候选题">
          <label>
            <input
              :checked="currentBatchSelected"
              :data-testid="`batch-select-${selectedDraft.id}`"
              :disabled="writeControlsDisabled || !currentBatchSelectable"
              type="checkbox"
              @change="updateCurrentBatchSelection"
            >
            将此候选加入批量接受
          </label>
          <label v-if="currentBatchSelected && selectedValidation?.status === 'warning'">
            <input
              :checked="currentBatchWarningConfirmed"
              :data-testid="`batch-warning-${selectedDraft.id}`"
              :disabled="writeControlsDisabled"
              type="checkbox"
              @change="updateCurrentBatchWarning"
            >
            我已阅读此候选的 warning
          </label>
          <p>已选择 {{ selectedBatchDraftIds.length }} 道候选题。</p>
          <button
            :disabled="writeControlsDisabled || !batchSelectionReady"
            data-testid="bulk-accept-candidates"
            type="button"
            @click="acceptBatch"
          >
            批量接受并创建草稿
          </button>
        </section>
        <TeacherAiCandidateReview
          v-if="selectedDraft"
          :draft="selectedDraft"
          :validation="selectedValidation"
          :busy="writeControlsDisabled"
          :accepted-question-version-id="selectedAcceptedQuestionVersionId"
          @save-revision="saveRevision"
          @reject="rejectCandidate"
          @accept="acceptCandidate"
          @regenerate="regenerateCandidate"
        />
        <p v-else-if="!loading">请选择要审核的候选题。</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.ai-review-workspace__grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.32fr) minmax(0, 1fr);
  gap: 24px;
  margin-top: 32px;
}

.ai-review-workspace__grid ul {
  display: grid;
  gap: 8px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.ai-review-workspace__grid button {
  width: 100%;
}

.ai-review-workspace__review {
  display: grid;
  gap: 20px;
  min-width: 0;
}

.batch-review-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border, #d8dee8);
}

.batch-review-controls p {
  margin: 0;
}

@media (max-width: 760px) {
  .ai-review-workspace__grid {
    grid-template-columns: 1fr;
  }
}
</style>
