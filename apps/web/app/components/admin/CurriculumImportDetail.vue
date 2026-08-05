<template>
  <section class="stack" aria-labelledby="curriculum-import-detail-heading">
    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <p v-if="loading">正在加载导入批次…</p>
    <template v-else-if="batch">
      <div>
        <p class="eyebrow">导入批次</p>
        <h1 id="curriculum-import-detail-heading">{{ batch.profile.name }} / {{ batch.input_format }}</h1>
        <p>状态：{{ batch.status }} · {{ batch.change_summary }}</p>
      </div>

      <section class="notice" aria-labelledby="curriculum-import-summary-heading">
        <h2 id="curriculum-import-summary-heading">变更摘要</h2>
        <pre>{{ JSON.stringify(batch.summary, null, 2) }}</pre>
      </section>

      <section v-if="batch.proposed_objectives.length" class="notice" aria-labelledby="curriculum-proposed-objectives-heading">
        <h2 id="curriculum-proposed-objectives-heading">拟议课程目标</h2>
        <ul>
          <li v-for="objective in batch.proposed_objectives" :key="String(objective.code)">
            {{ objective.code }} · {{ objective.subject }} · {{ objective.domain }} · {{ objective.text }}
          </li>
        </ul>
      </section>

      <section v-if="batch.issues.length" class="notice" role="alert" aria-labelledby="curriculum-import-issues-heading">
        <h2 id="curriculum-import-issues-heading">导入问题</h2>
        <ul>
          <li v-for="issue in batch.issues" :key="`${issue.code}-${issue.source_path ?? ''}-${issue.source_row ?? ''}`">
            <code>{{ issue.code }}</code>：{{ issue.message }}
            <span v-if="issue.source_path || issue.source_row || issue.source_column">
              （位置：{{ issue.source_path ?? '文档' }}<template v-if="issue.source_row">，第 {{ issue.source_row }} 行</template><template v-if="issue.source_column">，{{ issue.source_column }} 列</template>）
            </span>
          </li>
        </ul>
      </section>

      <div class="actions">
        <button v-if="canSubmit" class="button primary" data-testid="submit-curriculum-review" type="button" :disabled="busy" @click="submitReview">
          提交审核
        </button>
        <template v-if="canReview">
          <button class="button primary" data-testid="approve-curriculum-import" type="button" :disabled="busy" @click="review(true)">审核通过</button>
          <button class="button secondary" data-testid="reject-curriculum-import" type="button" :disabled="busy" @click="review(false)">驳回并退休</button>
        </template>
        <template v-if="canActivate">
          <button class="button primary" data-testid="activate-curriculum-import" type="button" :disabled="busy" @click="activate">激活目录</button>
        </template>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchCurrentPrincipal, type CurrentPrincipal } from '../../lib/student-api'
import {
  activateCurriculumImport,
  fetchCurriculumImport,
  reviewCurriculumImport,
  submitCurriculumImportReview,
  type CurriculumImportDetail,
} from '../../lib/admin-curriculum'

const props = defineProps<{ batchId: string }>()
const batch = ref<CurriculumImportDetail | null>(null)
const principal = ref<CurrentPrincipal | null>(null)
const loading = ref(true)
const busy = ref(false)
const message = ref('')
const submitRequestKey = crypto.randomUUID()
const reviewRequestKey = crypto.randomUUID()
const activateRequestKey = crypto.randomUUID()

const canSubmit = computed(() => batch.value?.status === 'draft')
const canReview = computed(() => batch.value?.status === 'in_review' && !batch.value.reviewed_by_user_id && principal.value?.id !== batch.value.submitted_by_user_id)
const canActivate = computed(() => batch.value?.status === 'in_review' && principal.value?.id === batch.value.reviewed_by_user_id)

onMounted(async () => {
  try {
    const [nextBatch, nextPrincipal] = await Promise.all([
      fetchCurriculumImport($fetch, props.batchId),
      fetchCurrentPrincipal($fetch),
    ])
    batch.value = nextBatch
    principal.value = nextPrincipal
  } catch {
    message.value = '无法加载导入批次，请稍后重试。'
  } finally {
    loading.value = false
  }
})

async function actionToken(): Promise<string> {
  const current = principal.value ?? await fetchCurrentPrincipal($fetch)
  principal.value = current
  if (!current.csrf_token) throw new Error('当前会话缺少 CSRF token')
  return current.csrf_token
}

async function submitReview(): Promise<void> {
  if (!canSubmit.value) return
  await runAction(async () => submitCurriculumImportReview($fetch, await actionToken(), submitRequestKey, props.batchId))
}

async function review(approve: boolean): Promise<void> {
  if (!canReview.value) return
  await runAction(async () => reviewCurriculumImport($fetch, await actionToken(), reviewRequestKey, props.batchId, approve))
}

async function activate(): Promise<void> {
  if (!canActivate.value || !globalThis.confirm('确认激活此课程目录？')) return
  await runAction(async () => activateCurriculumImport($fetch, await actionToken(), activateRequestKey, props.batchId))
}

async function runAction(action: () => Promise<Partial<CurriculumImportDetail>>): Promise<void> {
  busy.value = true
  message.value = ''
  try {
    batch.value = { ...batch.value!, ...await action() }
  } catch (error) {
    message.value = typeof error === 'object' && error !== null && (error as { statusCode?: unknown }).statusCode === 409
      ? '批次状态已变化，请刷新后重试。'
      : '操作失败，请稍后重试。'
  } finally {
    busy.value = false
  }
}
</script>
