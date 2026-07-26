<script setup lang="ts">
import { computed, reactive, ref, toRaw, watch } from 'vue'

import {
  canAcceptCandidate,
  candidateEditInput,
  type TeacherAiCandidate,
  type TeacherAiDraft,
  type TeacherAiRejectReason,
  type TeacherAiValidationRun,
} from '../../lib/teacher-ai-review'
import { reviewPresentation } from '../../lib/teacher-ai-review-presentation'
import TeacherAiReviewDecision from './TeacherAiReviewDecision.vue'

const props = withDefaults(defineProps<{
  draft: TeacherAiDraft
  validation?: TeacherAiValidationRun | null
  busy?: boolean
  acceptedQuestionVersionId?: string | null
  hasNextReviewCandidate?: boolean
}>(), {
  validation: null,
  busy: false,
  acceptedQuestionVersionId: null,
  hasNextReviewCandidate: false,
})

const emit = defineEmits<{
  'save-revision': [candidate: TeacherAiCandidate]
  reject: [reason: TeacherAiRejectReason, detail: string]
  accept: [input: { confirmWarnings: boolean }]
  regenerate: []
  'continue-review': []
}>()

const candidate = reactive(structuredClone(toRaw(props.draft.candidate)))
const warningConfirmed = ref(false)
const rejectReason = ref<TeacherAiRejectReason>('incorrect_answer')
const rejectDetail = ref('')
const rejectError = ref('')
const saveError = ref('')
const ruleJson = ref(formatRuleJson(candidate.rule_json))
const accepted = computed(() => props.draft.teacher_state === 'accepted' || Boolean(props.acceptedQuestionVersionId))
const pendingReview = computed(() => !accepted.value && props.draft.teacher_state === 'pending_review')
const rejected = computed(() => !accepted.value && props.draft.teacher_state === 'rejected')
const canRegenerate = computed(() => pendingReview.value || rejected.value)
const reviewDraft = computed<TeacherAiDraft>(() => accepted.value
  ? { ...props.draft, teacher_state: 'accepted' }
  : props.draft)
const writeDisabled = computed(() => props.busy || !pendingReview.value)
const presentation = computed(() => reviewPresentation(reviewDraft.value, props.validation))

const canAccept = computed(() => canAcceptCandidate({
  teacher_state: props.draft.teacher_state,
  validation: props.validation,
  warningConfirmed: warningConfirmed.value,
}))

watch(() => props.draft, (draft) => {
  Object.assign(candidate, structuredClone(toRaw(draft.candidate)))
  ruleJson.value = formatRuleJson(candidate.rule_json)
  warningConfirmed.value = false
  rejectReason.value = 'incorrect_answer'
  rejectDetail.value = ''
  rejectError.value = ''
  saveError.value = ''
})

watch([rejectReason, rejectDetail], () => {
  rejectError.value = ''
})

function saveRevision() {
  if (writeDisabled.value) return
  try {
    const updatedCandidate = candidateEditInput(props.draft.candidate, {
      prompt: candidate.prompt,
      rule_json: parseRuleJson(ruleJson.value),
      explanation: candidate.explanation,
      knowledge_point: candidate.knowledge_point,
      difficulty: candidate.difficulty,
      reading_material: candidate.question_type === 'E4' ? candidate.reading_material : null,
    })
    saveError.value = ''
    emit('save-revision', updatedCandidate)
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '无法保存修订'
  }
}

function formatRuleJson(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2)
}

function parseRuleJson(value: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    return parsed as Record<string, unknown>
  } catch {
    throw new Error('评分规则必须是有效的 JSON 对象')
  }
}

function rejectCandidate() {
  if (writeDisabled.value) return
  const detail = rejectReason.value === 'other' ? rejectDetail.value.trim() : ''
  if (rejectReason.value === 'other' && !detail) {
    rejectError.value = '选择“其他”时，请填写拒绝详情。'
    return
  }
  if (detail.length > 500) {
    rejectError.value = '拒绝详情不能超过 500 个字符。'
    return
  }
  rejectError.value = ''
  emit('reject', rejectReason.value, detail)
}

function acceptCandidate() {
  if (!writeDisabled.value && canAccept.value) emit('accept', { confirmWarnings: warningConfirmed.value })
}

function regenerateCandidate() {
  if (!props.busy && canRegenerate.value) emit('regenerate')
}
</script>

<template>
  <section class="ai-candidate-review" aria-label="AI 候选题审核">
    <div v-if="accepted" data-testid="accepted-notice" role="status">
      <p>该候选题已接受，已创建题库草稿。</p>
      <p v-if="acceptedQuestionVersionId">
        QuestionVersion：<code data-testid="accepted-question-version-id">{{ acceptedQuestionVersionId }}</code>
      </p>
      <a data-testid="question-bank-link" href="/teacher#questions">前往题库工作台</a>
    </div>
    <p v-else-if="draft.teacher_state === 'rejected'" data-testid="rejected-notice" role="status">该候选题已拒绝。</p>

    <section data-testid="review-student-preview" aria-labelledby="student-preview-heading">
      <section data-testid="ai-review-preview" class="ai-candidate-review__preview">
        <p class="eyebrow">当前候选题 · 第 {{ draft.ordinal }} 题</p>
        <h2 id="student-preview-heading">学生将看到的题目</h2>
        <p>{{ candidate.prompt }}</p>
        <section v-if="candidate.question_type === 'E4'" data-testid="reading-material" aria-label="阅读材料预览">
          <h3>阅读材料</h3>
          <p>{{ candidate.reading_material }}</p>
        </section>
        <p>知识点：{{ candidate.knowledge_point }} · 目标难度：{{ candidate.difficulty }}</p>
      </section>
    </section>

    <section data-testid="review-decision" aria-live="polite">
      <TeacherAiReviewDecision :draft="reviewDraft" :validation="validation" />
      <p v-if="presentation.kind === 'needs_fix'" data-testid="blocked-primary-action">
        下一步：{{ presentation.primaryAction }}。在下方修改题目后保存，系统会重新校验。
      </p>
      <label v-if="presentation.kind === 'needs_confirmation'">
        <input v-model="warningConfirmed" :disabled="writeDisabled" aria-label="确认 warning 后接受" type="checkbox"> 我已阅读此提醒
      </label>
      <button
        v-if="presentation.kind === 'ready' || presentation.kind === 'needs_confirmation'"
        :disabled="writeDisabled || !canAccept"
        data-testid="accept-candidate"
        type="button"
        @click="acceptCandidate"
      >
        接受为题库草稿
      </button>
    </section>

    <details v-if="pendingReview" data-testid="edit-candidate-details" class="ai-candidate-review__editor">
      <summary>修改题目并重新校验</summary>
      <p>保存后会重新校验此候选题；校验通过或完成 warning 确认后才能接受。</p>
      <fieldset>
        <legend>候选题信息</legend>
        <label>题型<input :value="candidate.question_type" aria-label="题型" readonly></label>
        <label>目标修订<input :value="candidate.objective_revision_id" aria-label="目标修订" readonly></label>
        <label>策略版本<input :value="candidate.policy_version" aria-label="策略版本" readonly></label>
      </fieldset>
      <label>题目提示<textarea v-model="candidate.prompt" :disabled="writeDisabled" aria-label="题目提示" /></label>
      <label>评分规则 JSON<textarea v-model="ruleJson" :disabled="writeDisabled" aria-label="评分规则 JSON" /></label>
      <label>解析<textarea v-model="candidate.explanation" :disabled="writeDisabled" aria-label="解析" /></label>
      <label>知识点<input v-model="candidate.knowledge_point" :disabled="writeDisabled" aria-label="知识点"></label>
      <label>难度<input v-model.number="candidate.difficulty" :disabled="writeDisabled" aria-label="难度" max="1" min="0" step="0.1" type="number"></label>
      <label v-if="candidate.question_type === 'E4'">阅读材料<textarea v-model="candidate.reading_material" :disabled="writeDisabled" aria-label="阅读材料" /></label>
      <p v-if="saveError" role="alert">{{ saveError }}</p>
      <button :disabled="writeDisabled" data-testid="save-revision" type="button" @click="saveRevision">保存并重新校验</button>
    </details>

    <template v-if="pendingReview">
      <label>拒绝原因
        <select v-model="rejectReason" :disabled="writeDisabled" aria-label="拒绝原因">
          <option value="incorrect_answer">答案错误</option>
          <option value="out_of_scope">超纲</option>
          <option value="unclear_wording">表述不清</option>
          <option value="duplicate">重复</option>
          <option value="unsuitable_for_students">不适合学生</option>
          <option value="other">其他</option>
        </select>
      </label>
      <label v-if="rejectReason === 'other'">拒绝详情<textarea v-model="rejectDetail" :disabled="writeDisabled" aria-label="拒绝详情" maxlength="500" /></label>
      <p v-if="rejectError" data-testid="reject-detail-error" role="alert">{{ rejectError }}</p>
      <button :disabled="writeDisabled" data-testid="reject-candidate" type="button" @click="rejectCandidate">拒绝候选题</button>
    </template>

    <template v-if="canRegenerate">
      <button :disabled="busy" data-testid="regenerate-candidate" type="button" @click="regenerateCandidate">
        {{ rejected ? '重新生成同题型候选题' : '重新生成' }}
      </button>
    </template>
    <template v-if="rejected">
      <button
        v-if="hasNextReviewCandidate"
        :disabled="busy"
        data-testid="continue-review-next-candidate"
        type="button"
        @click="emit('continue-review')"
      >
        继续审核下一题
      </button>
      <NuxtLink v-else data-testid="generate-new-ai-batch" to="/teacher/ai-questions/new">生成新批次</NuxtLink>
    </template>

    <section data-testid="technical-review-details" class="ai-candidate-review__advanced">
      <details data-testid="advanced-review-information">
        <summary>高级信息：评分规则与技术记录</summary>
        <section aria-label="候选题审计记录">
          <p>题型：{{ candidate.question_type }}</p>
          <p>目标修订：{{ candidate.objective_revision_id }}</p>
          <p>策略版本：{{ candidate.policy_version }}</p>
        </section>
        <section v-if="validation" aria-label="校验结果">
          <p>校验状态：{{ validation.status }}</p>
          <ul>
            <li v-for="finding in validation.findings" :key="finding.code" data-testid="validation-finding">
              <strong>{{ finding.code }}</strong>
              <span>{{ finding.remediation }}</span>
              <pre>{{ JSON.stringify(finding.evidence, null, 2) }}</pre>
            </li>
          </ul>
        </section>
        <pre>{{ ruleJson }}</pre>
      </details>
    </section>
  </section>
</template>

<style scoped>
.ai-candidate-review { display: grid; gap: 18px; }
.ai-candidate-review__preview, .ai-candidate-review__advanced, .ai-candidate-review__editor { padding: 20px; border: 1px solid #e1e7f0; border-radius: 16px; background: #fff; }
.ai-candidate-review h2 { margin: 0; font-size: 1.45rem; line-height: 1.4; }
.ai-candidate-review h3 { margin: 18px 0 8px; font-size: 1rem; }
.ai-candidate-review label { display: grid; gap: 6px; margin-top: 14px; color: #35435a; font-weight: 750; }
.ai-candidate-review input, .ai-candidate-review select, .ai-candidate-review textarea { width: 100%; padding: 10px 12px; border: 1px solid #cbd6e6; border-radius: 10px; background: #fff; color: #152033; font: inherit; }
.ai-candidate-review textarea { min-height: 92px; resize: vertical; }
.ai-candidate-review summary { min-height: 44px; cursor: pointer; color: #2459c4; font-weight: 850; }
.ai-candidate-review fieldset { display: grid; gap: 10px; margin-top: 16px; }
.ai-candidate-review button { min-height: 44px; margin-top: 14px; padding: 0 16px; border: 1px solid #2459c4; border-radius: 10px; background: #fff; color: #2459c4; font: inherit; font-weight: 800; cursor: pointer; }
.ai-candidate-review button:disabled { border-color: #d6deea; background: #f4f6fa; color: #9aa7ba; cursor: not-allowed; }
.ai-candidate-review pre { overflow: auto; padding: 12px; border-radius: 10px; background: #f5f7fb; white-space: pre-wrap; }
</style>
