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

const props = withDefaults(defineProps<{
  draft: TeacherAiDraft
  validation?: TeacherAiValidationRun | null
  busy?: boolean
  acceptedQuestionVersionId?: string | null
}>(), {
  validation: null,
  busy: false,
  acceptedQuestionVersionId: null,
})

const emit = defineEmits<{
  'save-revision': [candidate: TeacherAiCandidate]
  reject: [reason: TeacherAiRejectReason, detail: string]
  accept: [input: { confirmWarnings: boolean }]
  regenerate: []
}>()

const candidate = reactive(structuredClone(toRaw(props.draft.candidate)))
const warningConfirmed = ref(false)
const rejectReason = ref<TeacherAiRejectReason>('incorrect_answer')
const rejectDetail = ref('')
const rejectError = ref('')
const saveError = ref('')
const ruleJson = ref(formatRuleJson(candidate.rule_json))
const accepted = computed(() => props.draft.teacher_state === 'accepted' || Boolean(props.acceptedQuestionVersionId))
const writeDisabled = computed(() => props.busy || accepted.value || props.draft.teacher_state !== 'pending_review')

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
  if (!writeDisabled.value) emit('regenerate')
}
</script>

<template>
  <section aria-label="AI 候选题审核">
    <div v-if="accepted" data-testid="accepted-notice" role="status">
      <p>该候选题已接受，已创建题库草稿。</p>
      <p v-if="acceptedQuestionVersionId">
        QuestionVersion：<code data-testid="accepted-question-version-id">{{ acceptedQuestionVersionId }}</code>
      </p>
      <a data-testid="question-bank-link" href="/teacher#questions">前往题库工作台</a>
    </div>
    <p v-else-if="draft.teacher_state === 'rejected'" data-testid="rejected-notice" role="status">该候选题已拒绝。</p>

    <fieldset>
      <legend>候选题信息</legend>
      <label>题型<input :value="candidate.question_type" aria-label="题型" readonly></label>
      <label>目标修订<input :value="candidate.objective_revision_id" aria-label="目标修订" readonly></label>
      <label>策略版本<input :value="candidate.policy_version" aria-label="策略版本" readonly></label>
    </fieldset>

    <section v-if="candidate.question_type === 'E4'" data-testid="reading-material" aria-label="阅读材料预览">
      <h2>阅读材料</h2>
      <p>{{ candidate.reading_material }}</p>
    </section>

    <label>题目提示<textarea v-model="candidate.prompt" :disabled="writeDisabled" aria-label="题目提示" /></label>
    <label>评分规则 JSON<textarea v-model="ruleJson" :disabled="writeDisabled" aria-label="评分规则 JSON" /></label>
    <label>解析<textarea v-model="candidate.explanation" :disabled="writeDisabled" aria-label="解析" /></label>
    <label>知识点<input v-model="candidate.knowledge_point" :disabled="writeDisabled" aria-label="知识点"></label>
    <label>难度<input v-model.number="candidate.difficulty" :disabled="writeDisabled" aria-label="难度" max="1" min="0" step="0.1" type="number"></label>
    <label v-if="candidate.question_type === 'E4'">阅读材料<textarea v-model="candidate.reading_material" :disabled="writeDisabled" aria-label="阅读材料" /></label>
    <p v-if="saveError" role="alert">{{ saveError }}</p>
    <button :disabled="writeDisabled" data-testid="save-revision" type="button" @click="saveRevision">保存修订</button>
    <button
      v-if="draft.teacher_state === 'pending_review'"
      :disabled="writeDisabled"
      data-testid="regenerate-candidate"
      type="button"
      @click="regenerateCandidate"
    >
      重新生成
    </button>

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

    <label v-if="validation?.status === 'warning'">
      <input v-model="warningConfirmed" :disabled="writeDisabled" aria-label="确认 warning 后接受" type="checkbox"> 我已阅读 warning
    </label>
    <button :disabled="writeDisabled || !canAccept" data-testid="accept-candidate" type="button" @click="acceptCandidate">接受并创建草稿</button>

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
  </section>
</template>
