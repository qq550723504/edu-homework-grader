<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  acceptAiCandidate,
  fetchAiGenerationDrafts,
  fetchAiGenerationJobs,
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
const validations = ref<Record<string, TeacherAiValidationRun>>({})
const loading = ref(false)
const busyOperation = ref<'save' | 'reject' | 'accept' | null>(null)
const notice = ref('')
const errorMessage = ref('')
let loadSequence = 0

const selectedJobId = computed(() => queryValue(route.query.job))
const selectedDraftId = computed(() => queryValue(route.query.draft))
const selectedDraft = computed(() => drafts.value.find((draft) => draft.id === selectedDraftId.value) ?? null)
const selectedValidation = computed(() => selectedDraft.value ? validations.value[selectedDraft.value.id] ?? null : null)

function queryValue(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

async function loadWorkspace() {
  const sequence = ++loadSequence
  loading.value = true
  errorMessage.value = ''
  try {
    const nextJobs = await fetchAiGenerationJobs($fetch)
    const requestedJobId = queryValue(route.query.job)
    const jobId = nextJobs.some((job) => job.id === requestedJobId) ? requestedJobId : nextJobs[0]?.id ?? null
    const nextDrafts = jobId ? await fetchAiGenerationDrafts($fetch, jobId) : []
    if (sequence !== loadSequence) return

    jobs.value = nextJobs
    drafts.value = nextDrafts
    const requestedDraftId = queryValue(route.query.draft)
    const draftId = nextDrafts.some((draft) => draft.id === requestedDraftId)
      ? requestedDraftId
      : nextDrafts[0]?.id ?? null
    if (jobId !== requestedJobId || draftId !== requestedDraftId) {
      await navigateTo({ query: routeQuery(jobId, draftId) })
    }
  } catch (error: unknown) {
    if (sequence === loadSequence) errorMessage.value = publicErrorMessage(error)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function reloadDrafts() {
  const jobId = selectedJobId.value
  if (!jobId) return
  const nextDrafts = await fetchAiGenerationDrafts($fetch, jobId)
  drafts.value = nextDrafts
  const draftId = nextDrafts.some((draft) => draft.id === selectedDraftId.value)
    ? selectedDraftId.value
    : nextDrafts[0]?.id ?? null
  if (draftId !== selectedDraftId.value) {
    await navigateTo({ query: routeQuery(jobId, draftId) })
  }
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
  if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。')
  return principal.csrf_token
}

async function saveRevision(candidate: TeacherAiCandidate) {
  const draft = selectedDraft.value
  if (!draft || busyOperation.value) return
  await runWrite('save', async (csrf, key) => {
    const result = await saveAiCandidateRevision(
      $fetch, csrf, draft.id, key, draft.revision_number, candidate,
    )
    validations.value = { ...validations.value, [draft.id]: result.validation_run }
    return '候选修订已保存。'
  })
}

async function rejectCandidate(reason: TeacherAiRejectReason, detail: string) {
  const draft = selectedDraft.value
  if (!draft || busyOperation.value) return
  await runWrite('reject', async (csrf, key) => {
    const result = await rejectAiCandidate(
      $fetch, csrf, draft.id, key, draft.revision_number, reason, detail,
    )
    validations.value = { ...validations.value, [draft.id]: result.validation_run }
    return '候选题已拒绝。'
  })
}

async function acceptCandidate(input: { confirmWarnings: boolean }) {
  const draft = selectedDraft.value
  if (!draft || busyOperation.value) return
  await runWrite('accept', async (csrf, key) => {
    const result = await acceptAiCandidate(
      $fetch, csrf, draft.id, key, draft.revision_number, input.confirmWarnings,
    )
    validations.value = { ...validations.value, [draft.id]: result.validation_run }
    return '候选题已接受并创建草稿。'
  })
}

async function runWrite(
  operation: 'save' | 'reject' | 'accept',
  write: (csrf: string, key: string) => Promise<string>,
) {
  busyOperation.value = operation
  notice.value = ''
  errorMessage.value = ''
  try {
    const csrf = await csrfToken()
    const successMessage = await write(csrf, crypto.randomUUID())
    await reloadDrafts()
    notice.value = successMessage
  } catch (error: unknown) {
    if (isRevisionConflict(error)) {
      try {
        await reloadDrafts()
        notice.value = '候选已被更新，已加载最新修订。'
      } catch (reloadError: unknown) {
        errorMessage.value = publicErrorMessage(reloadError)
      }
    } else {
      errorMessage.value = publicErrorMessage(error)
    }
  } finally {
    busyOperation.value = null
  }
}

function isRevisionConflict(error: unknown): boolean {
  if (!isRecord(error) || !isRecord(error.data) || !isRecord(error.data.detail)) return false
  return error.data.detail.code === 'review_revision_conflict'
}

function publicErrorMessage(error: unknown): string {
  const status = errorStatus(error)
  if (status === 404) return '未找到所选的 AI 出题批次或候选题。'
  if (status === 429) return '请求过于频繁，请稍后重试。'
  if (status === 503) return 'AI 出题审核服务暂时不可用，请稍后重试。'
  if (error instanceof TypeError) return '网络连接异常，请检查网络后重试。'
  if (error instanceof Error && error.message) return error.message
  return '暂时无法读取 AI 出题审核数据，请稍后重试。'
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
    </header>

    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="errorMessage" class="notice" role="alert">{{ errorMessage }}</p>
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
          :busy="busyOperation !== null"
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
