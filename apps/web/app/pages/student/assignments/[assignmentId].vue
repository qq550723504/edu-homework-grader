<template>
  <main class="shell narrow"><NuxtLink class="back" to="/student">← 作业列表</NuxtLink><LogoutButton /><p class="eyebrow">{{ isCorrection ? '订正作答' : '作答中' }}</p><h1>{{ detail?.title ?? '加载作业…' }}</h1>
    <section v-if="feedback.length" aria-label="已发布反馈"><p v-for="(entry, index) in feedback" :key="index">{{ entry }}</p></section>
    <section v-if="feedback.length && !appealSubmitted && !isCorrection" class="card wide" aria-labelledby="appeal-heading"><h2 id="appeal-heading">对成绩有疑问？</h2><form class="stack" @submit.prevent="submitAppeal"><label>申诉理由<textarea v-model.trim="appealReason" aria-label="申诉理由" required maxlength="2000" rows="3" /></label><button class="button secondary" type="submit">提交申诉</button></form></section>
    <p v-if="hasPublishedCorrection" role="status">可以查看订正结果</p>
    <p v-if="message" class="notice">{{ message }}</p>
    <section v-if="currentItem" class="card wide"><span class="tag">第 {{ currentItem.position }} 题</span><div v-if="currentItem.reading_material" class="reading-material" style="white-space: pre-wrap">{{ currentItem.reading_material }}</div><h2>{{ currentItem.prompt }}</h2><MathAnswerField v-if="currentItem.input?.kind === 'mathjson-v1'" v-model="mathAnswer" :disabled="!writable || writesBlocked || !!conflict" @update:model-value="saveMathDraft" /><textarea v-else :value="answer" class="answer-input" rows="5" aria-label="答案" :disabled="!writable || writesBlocked || !!conflict" @input="saveDraft" /><p>同步状态：{{ syncStatus }}</p><div v-if="conflict" class="actions"><button class="button secondary" data-testid="use-server-answer" type="button" @click="useServerAnswer">采用服务器答案</button><button class="button secondary" data-testid="keep-local-answer" type="button" @click="keepLocalAnswer">保留我的答案</button></div><button v-if="retryExhausted" class="button secondary" data-testid="retry-sync" type="button" @click="retrySync">重新同步</button></section>
    <div class="actions"><button class="button secondary" :disabled="current === 0" @click="current = previousQuestionIndex(current)">上一题</button><button class="button secondary" :disabled="!detail || current >= detail.items.length - 1" @click="current = nextQuestionIndex(current, detail?.items.length ?? 0)">下一题</button><button class="button primary" :disabled="!writable || !online || unanswered > 0 || !canSubmit || writesBlocked || !!conflict" @click="submit">{{ isCorrection ? '提交订正' : '提交作业' }}</button></div><p v-if="unanswered > 0" class="notice">还有 {{ unanswered }} 题未作答</p>
  </main>
</template>
<script setup lang="ts">
import { canSubmitAttempt, flushAttempt, getDraft, getSubmissionKey, queueAnswer, requeueConflictWithLocal, resolveConflictWithServer, type DraftRecord } from '../../../lib/drafts'
import { classifyStudentSaveError, retryDelayMs, studentSyncMessage, type StudentSyncOutcome } from '../../../lib/student-sync'
import { correctionAvailable, fetchCurrentPrincipal, publishedFeedback, type CurrentPrincipal } from '../../../lib/student-api'
import { editorStateForItem, getUnansweredCount, isAssignmentWritable, nextQuestionIndex, previousQuestionIndex } from '../../../lib/student-workflow'
import type { MathAnswer } from '../../../lib/math-answer'

interface Item { id: string; position: number; prompt: string; reading_material: string | null; input: { kind: string }; answer: Record<string, unknown> | null; version: number }
interface Detail { id: string; title: string; status?: string; attempt: { id: string; attempt_number?: number; status?: string }; items: Item[]; grading?: Array<{ feedback?: Array<{ message?: string }> }>; corrections?: Array<{ attempt_id?: string; status?: string }> }

const route = useRoute()
const detail = ref<Detail | null>(null)
const principal = ref<CurrentPrincipal | null>(null)
const current = ref(0)
const answer = ref('')
const mathAnswer = ref<MathAnswer | null>(null)
const syncStatus = ref('未保存')
const message = ref('')
const appealReason = ref('')
const appealSubmitted = ref(false)
const online = ref(typeof window !== 'undefined' ? navigator.onLine : false)
const writesBlocked = ref(false)
const conflict = ref<DraftRecord | null>(null)
const retryExhausted = ref(false)
const canSubmit = ref(false)

const currentItem = computed(() => detail.value?.items[current.value])
const writable = computed(() => isAssignmentWritable(detail.value?.status))
const isCorrection = computed(() => (detail.value?.attempt.attempt_number ?? 1) > 1)
const unanswered = computed(() => detail.value ? getUnansweredCount(detail.value.items) : 0)
const feedback = computed(() => detail.value ? publishedFeedback(detail.value) : [])
const hasPublishedCorrection = computed(() => detail.value ? correctionAvailable(detail.value) : false)

let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryAttempt = 0
let abortController: AbortController | null = null
let sessionRefreshAttempted = false
let mounted = false

async function loadCurrentItemEditor() {
  const item = currentItem.value
  const savedDraft = item && detail.value && principal.value
    ? await getDraft(principal.value.tenant_id, principal.value.id, detail.value.attempt.id, item.id)
    : undefined
  if (!mounted || item !== currentItem.value) return
  const state = editorStateForItem(savedDraft ?? item)
  answer.value = state.text
  mathAnswer.value = state.mathAnswer as MathAnswer | null
}

function stopSyncWork() {
  if (retryTimer !== null) clearTimeout(retryTimer)
  retryTimer = null
  abortController?.abort()
  abortController = null
}

function startSaveRequest(): AbortSignal {
  abortController?.abort()
  abortController = new AbortController()
  return abortController.signal
}

async function saveAnswer(record: DraftRecord, csrfToken: string): Promise<{ version: number }> {
  return $fetch<{ version: number }>(
    `/api/core/v1/student/attempts/${record.attemptId}/answers/${record.itemId}`,
    {
      method: 'PUT',
      headers: { 'X-CSRF-Token': csrfToken },
      body: { answer: record.answer, version: record.version },
      signal: startSaveRequest()
    }
  )
}

async function redirectToLogin() {
  const fullPath = typeof route.fullPath === 'string'
    ? route.fullPath
    : `/student/assignments/${route.params.assignmentId}`
  await navigateTo(`/api/auth/login?returnTo=${encodeURIComponent(fullPath)}`, { external: true })
}

async function refreshSessionAndRetry(record: DraftRecord): Promise<StudentSyncOutcome> {
  if (sessionRefreshAttempted) return { kind: 'session_expired' }
  sessionRefreshAttempted = true
  try {
    const renewed = await fetchCurrentPrincipal($fetch)
    if (!renewed.csrf_token) throw new Error('missing csrf token')
    principal.value = renewed
    const saved = await saveAnswer(record, renewed.csrf_token)
    return { kind: 'saved', version: saved.version }
  } catch {
    await redirectToLogin()
    return { kind: 'session_expired' }
  }
}

function scheduleRetry(outcome: Extract<StudentSyncOutcome, { kind: 'rate_limited' | 'server_error' }>) {
  const delay = retryDelayMs(++retryAttempt, outcome.retryAfterMs)
  if (delay === null) {
    retryExhausted.value = true
    syncStatus.value = '自动重试已停止，请手动重试。'
    return
  }
  if (retryTimer !== null) clearTimeout(retryTimer)
  retryTimer = setTimeout(() => { void sync() }, delay)
}

async function sync() {
  if (!detail.value || !online.value || !principal.value?.csrf_token || writesBlocked.value || conflict.value) return
  let outcome: StudentSyncOutcome | null = null
  let conflicting: DraftRecord | null = null
  await flushAttempt(detail.value.attempt.id, {
    saveAnswer: async (record) => {
      try {
        const saved = await saveAnswer(record, principal.value!.csrf_token!)
        outcome = { kind: 'saved', version: saved.version }
      } catch (error: unknown) {
        outcome = classifyStudentSaveError(error)
        if (outcome.kind === 'session_expired') outcome = await refreshSessionAndRetry(record)
        if (outcome.kind === 'conflict') {
          conflicting = { ...record, status: 'conflict', serverAnswer: outcome.current.answer, serverVersion: outcome.current.version }
        }
      }
      return outcome!
    }
  }, {
    onSaved: (record, version) => {
      const item = detail.value?.items.find((candidate) => candidate.id === record.itemId)
      if (item) item.version = version
    }
  })
  if (!mounted) return
  await refreshSubmit()
  if (!outcome) return
  syncStatus.value = studentSyncMessage(outcome)
  writesBlocked.value = outcome.kind === 'processing_blocked' || outcome.kind === 'session_expired'
  conflict.value = conflicting
  if (outcome.kind === 'saved') {
    retryAttempt = 0
    retryExhausted.value = false
  }
  if (outcome.kind === 'rate_limited' || outcome.kind === 'server_error') scheduleRetry(outcome)
}

async function useServerAnswer() {
  if (!conflict.value) return
  await resolveConflictWithServer(conflict.value)
  conflict.value = null
  syncStatus.value = '已采用服务器答案。'
  await refreshSubmit()
}

async function keepLocalAnswer() {
  if (!conflict.value) return
  await requeueConflictWithLocal(conflict.value)
  conflict.value = null
  syncStatus.value = '已保留本机答案，等待同步。'
  await sync()
}

async function retrySync() {
  retryAttempt = 0
  retryExhausted.value = false
  await sync()
}

async function refreshSubmit() {
  canSubmit.value = detail.value ? await canSubmitAttempt(detail.value.attempt.id) : false
}

async function saveDraft(event: Event) {
  answer.value = (event.target as HTMLTextAreaElement).value
  if (!writable.value || !detail.value || !currentItem.value || !principal.value || writesBlocked.value || conflict.value) return
  const textAnswer = { format: 'text-v1', text: answer.value }
  currentItem.value.answer = textAnswer
  await queueAnswer({ tenantId: principal.value.tenant_id, userId: principal.value.id, attemptId: detail.value.attempt.id, itemId: currentItem.value.id, answer: textAnswer, version: currentItem.value.version })
  syncStatus.value = '已保存到本机，等待同步'
  await sync()
}

async function saveMathDraft(value: MathAnswer | null) {
  mathAnswer.value = value
  if (!value) { syncStatus.value = '公式尚不完整，未保存'; return }
  if (!writable.value || !detail.value || !currentItem.value || !principal.value || writesBlocked.value || conflict.value) return
  currentItem.value.answer = value
  await queueAnswer({ tenantId: principal.value.tenant_id, userId: principal.value.id, attemptId: detail.value.attempt.id, itemId: currentItem.value.id, answer: value, version: currentItem.value.version })
  syncStatus.value = '已保存到本机，等待同步'
  await sync()
}

async function submit() {
  if (!detail.value || !principal.value?.csrf_token || writesBlocked.value || conflict.value) return
  await sync()
  if (!await canSubmitAttempt(detail.value.attempt.id)) return
  const key = await getSubmissionKey(detail.value.attempt.id)
  const endpoint = isCorrection.value
    ? `/api/core/v1/student/attempts/${detail.value.attempt.id}/submit`
    : `/api/core/v1/student/assignments/${detail.value.id}/submit`
  await $fetch(endpoint, { method: 'POST', headers: { 'Idempotency-Key': key, 'X-CSRF-Token': principal.value.csrf_token } })
  detail.value.attempt.status = 'submitted'
  detail.value.status = isCorrection.value ? 'correction_pending_review' : 'submitted_pending_review'
  canSubmit.value = false
  syncStatus.value = isCorrection.value ? '订正已提交，等待教师复核' : '已提交'
}

async function submitAppeal() {
  if (!detail.value || !principal.value?.csrf_token) return
  try {
    await $fetch(`/api/core/v1/student/attempts/${detail.value.attempt.id}/appeals`, { method: 'POST', headers: { 'X-CSRF-Token': principal.value.csrf_token }, body: { reason: appealReason.value } })
    appealSubmitted.value = true
    message.value = '申诉已提交，教师会查看评分证据后处理。'
  } catch (error: any) {
    message.value = error?.data?.detail ?? '暂时无法提交申诉。'
  }
}

function onOnline() { online.value = true; void sync() }
function onOffline() { online.value = false; syncStatus.value = '网络不可用，答案已保存在本机。' }
function onVisibilityChange() { if (document.visibilityState === 'hidden') void sync() }

watch(currentItem, () => { void loadCurrentItemEditor() })
onMounted(async () => {
  abortController = new AbortController()
  mounted = true
  try {
    const [identity, assignment] = await Promise.all([fetchCurrentPrincipal($fetch), $fetch<Detail>(`/api/core/v1/student/assignments/${route.params.assignmentId}`)])
    principal.value = identity
    detail.value = assignment
    await loadCurrentItemEditor()
    await refreshSubmit()
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    window.addEventListener('visibilitychange', onVisibilityChange)
  } catch {
    message.value = '暂时无法读取作业。'
  }
})
onBeforeUnmount(() => {
  mounted = false
  stopSyncWork()
  window.removeEventListener('online', onOnline)
  window.removeEventListener('offline', onOffline)
  window.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>
