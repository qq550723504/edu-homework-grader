<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  acceptAiCandidate,
  fetchAiGenerationDrafts,
  fetchAiGenerationJobs,
  fetchAiValidationRuns,
  rejectAiCandidate,
  saveAiCandidateRevision,
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
const loading = ref(false)
const refreshing = ref(false)
const busyOperation = ref<'save' | 'reject' | 'accept' | null>(null)
const notice = ref('')
const errorMessage = ref('')
const syncWarning = ref('')
const pendingRefresh = ref<{
  jobId: string
  draftId: string
  idempotencyKey: string
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
  const validation = draft ? await fetchCurrentValidation(draft) : null
  if (!refreshIsCurrent(generation, owningRouteGeneration, jobId, draftId)) return 'stale'

  drafts.value = nextDrafts
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
    try {
      const refresh = await refreshSelection(jobId, draft.id, result.validation.revision_number)
      if (refresh === 'updated') pendingRefresh.value = null
      if (refresh === 'behind') deferRefresh(jobId, draft.id, idempotencyKey)
    } catch {
      if (requestMatches(jobId, draft.id)) deferRefresh(jobId, draft.id, idempotencyKey)
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
  return updatedDraft
}

function deferRefresh(jobId: string, draftId: string, idempotencyKey: string) {
  pendingRefresh.value = { jobId, draftId, idempotencyKey }
  syncWarning.value = '操作已成功，但最新审核状态暂时无法刷新。请重试刷新。'
}

async function retryRefresh() {
  const pending = pendingRefresh.value
  if (!pending || !requestMatches(pending.jobId, pending.draftId)) return
  const operationIdentity = pending.idempotencyKey
  refreshing.value = true
  try {
    const refresh = await refreshSelection(pending.jobId, pending.draftId)
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
        <TeacherAiCandidateReview
          v-if="selectedDraft"
          :draft="selectedDraft"
          :validation="selectedValidation"
          :busy="writeControlsDisabled"
          :accepted-question-version-id="selectedAcceptedQuestionVersionId"
          @save-revision="saveRevision"
          @reject="rejectCandidate"
          @accept="acceptCandidate"
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
  min-width: 0;
}

@media (max-width: 760px) {
  .ai-review-workspace__grid {
    grid-template-columns: 1fr;
  }
}
</style>
