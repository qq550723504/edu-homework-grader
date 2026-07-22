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
}>(), {
  validation: null,
  busy: false,
})

const emit = defineEmits<{
  'save-revision': [candidate: TeacherAiCandidate]
  reject: [reason: TeacherAiRejectReason, detail: string]
  accept: [input: { confirmWarnings: boolean }]
}>()

const candidate = reactive(structuredClone(toRaw(props.draft.candidate)))
const warningConfirmed = ref(false)
const rejectReason = ref<TeacherAiRejectReason>('incorrect_answer')
const rejectDetail = ref('')
const saveError = ref('')
const ruleJson = ref(formatRuleJson(candidate.rule_json))

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
  saveError.value = ''
})

function saveRevision() {
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
  emit('reject', rejectReason.value, rejectDetail.value)
}

function acceptCandidate() {
  if (canAccept.value) emit('accept', { confirmWarnings: warningConfirmed.value })
}
</script>

<template>
  <section aria-label="AI 候选题审核">
    <p v-if="draft.teacher_state === 'accepted'" data-testid="accepted-notice" role="status">该候选题已接受。</p>

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

    <label>题目提示<textarea v-model="candidate.prompt" aria-label="题目提示" /></label>
    <label>评分规则 JSON<textarea v-model="ruleJson" aria-label="评分规则 JSON" /></label>
    <label>解析<textarea v-model="candidate.explanation" aria-label="解析" /></label>
    <label>知识点<input v-model="candidate.knowledge_point" aria-label="知识点"></label>
    <label>难度<input v-model.number="candidate.difficulty" aria-label="难度" max="1" min="0" step="0.1" type="number"></label>
    <label v-if="candidate.question_type === 'E4'">阅读材料<textarea v-model="candidate.reading_material" aria-label="阅读材料" /></label>
    <p v-if="saveError" role="alert">{{ saveError }}</p>
    <button :disabled="busy" data-testid="save-revision" type="button" @click="saveRevision">保存修订</button>

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
      <input v-model="warningConfirmed" aria-label="确认 warning 后接受" type="checkbox"> 我已阅读 warning
    </label>
    <button :disabled="busy || !canAccept" data-testid="accept-candidate" type="button" @click="acceptCandidate">接受并创建草稿</button>

    <label>拒绝原因
      <select v-model="rejectReason" aria-label="拒绝原因">
        <option value="incorrect_answer">答案错误</option>
        <option value="out_of_scope">超纲</option>
        <option value="unclear_wording">表述不清</option>
        <option value="duplicate">重复</option>
        <option value="unsuitable_for_students">不适合学生</option>
        <option value="other">其他</option>
      </select>
    </label>
    <label>拒绝详情<textarea v-model="rejectDetail" aria-label="拒绝详情" /></label>
    <button :disabled="busy" data-testid="reject-candidate" type="button" @click="rejectCandidate">拒绝候选题</button>
  </section>
</template>
