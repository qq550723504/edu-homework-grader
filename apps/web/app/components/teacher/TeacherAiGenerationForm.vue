<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  createAiGenerationJob,
  expandGenerationPlanCounts,
  fetchCurriculumGradeMappings,
  fetchCurriculumObjectives,
  fetchCurriculumProfiles,
  fetchGenerationLimits,
  teacherAiDifficultyBands,
  teacherAiQuestionTypes,
  type CurriculumGradeMapping,
  type CurriculumObjective,
  type CurriculumProfile,
  type CreateAiGenerationJobInput,
  type GenerationLimits,
  type TeacherAiDifficultyBand,
  type TeacherAiQuestionType,
} from '../../lib/teacher-ai-generation'
import { fetchCurrentPrincipal } from '../../lib/student-api'

const profiles = ref<CurriculumProfile[]>([])
const grades = ref<CurriculumGradeMapping[]>([])
const objectives = ref<CurriculumObjective[]>([])
const subjects = ref<string[]>([])
const limits = ref<GenerationLimits | null>(null)
const selectedProfile = ref('')
const selectedGrade = ref('')
const selectedSubject = ref('')
const selectedObjectiveRevisionId = ref('')
type GenerationPlanCounts = Partial<Record<
  TeacherAiQuestionType,
  Partial<Record<TeacherAiDifficultyBand, number>>
>>

const counts = ref<GenerationPlanCounts>({})
const teacherConstraint = ref('')
const catalogLoading = ref(false)
const limitsLoading = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const pendingGenerationRequest = ref<{ intent: string, idempotencyKey: string } | null>(null)
let catalogGeneration = 0

const selectedObjective = computed(() => objectives.value.find(
  (objective) => objective.revision.id === selectedObjectiveRevisionId.value,
) ?? null)
const allowedTypes = computed(() => selectedObjective.value?.revision.allowed_question_types ?? [])
const requestedItems = computed(() => expandGenerationPlanCounts(counts.value))
const requestedCount = computed(() => requestedItems.value.length)
const maximumCount = computed(() => limits.value
  ? Math.min(limits.value.max_batch_size, limits.value.remaining_count)
  : 0)
const hasDisallowedType = computed(() => teacherAiQuestionTypes.some((type) => (
  Object.values(counts.value[type] ?? {}).some((count) => (count ?? 0) > 0)
  && !allowedTypes.value.includes(type)
)))
const createDisabled = computed(() => catalogLoading.value
  || limitsLoading.value
  || submitting.value
  || !selectedObjective.value
  || requestedCount.value === 0
  || hasDisallowedType.value
  || requestedCount.value > maximumCount.value)

onMounted(async () => {
  catalogLoading.value = true
  limitsLoading.value = true
  try {
    const [nextProfiles, nextLimits] = await Promise.all([
      fetchCurriculumProfiles($fetch),
      fetchGenerationLimits($fetch),
    ])
    profiles.value = nextProfiles
    limits.value = nextLimits
  } catch (error: unknown) {
    errorMessage.value = publicErrorMessage(error, '暂时无法读取 AI 出题配置，请稍后重试。')
  } finally {
    catalogLoading.value = false
    limitsLoading.value = false
  }
})

async function selectProfile() {
  const profile = selectedProfile.value
  const generation = ++catalogGeneration
  clearPendingGenerationRequest()
  selectedGrade.value = ''
  selectedSubject.value = ''
  selectedObjectiveRevisionId.value = ''
  grades.value = []
  subjects.value = []
  objectives.value = []
  resetCounts()
  if (!profile) {
    catalogLoading.value = false
    return
  }
  catalogLoading.value = true
  errorMessage.value = ''
  try {
    const nextGrades = await fetchCurriculumGradeMappings($fetch, profile)
    if (generation === catalogGeneration && selectedProfile.value === profile) grades.value = nextGrades
  } catch (error: unknown) {
    if (generation === catalogGeneration) errorMessage.value = publicErrorMessage(error, '暂时无法读取年级目录，请稍后重试。')
  } finally {
    if (generation === catalogGeneration) catalogLoading.value = false
  }
}

async function selectGrade() {
  const profile = selectedProfile.value
  const grade = selectedGrade.value
  const generation = ++catalogGeneration
  clearPendingGenerationRequest()
  selectedSubject.value = ''
  selectedObjectiveRevisionId.value = ''
  subjects.value = []
  objectives.value = []
  resetCounts()
  if (!profile || !grade) {
    catalogLoading.value = false
    return
  }
  catalogLoading.value = true
  errorMessage.value = ''
  try {
    const nextObjectives = await fetchCurriculumObjectives($fetch, profile, grade)
    if (generation !== catalogGeneration || selectedProfile.value !== profile || selectedGrade.value !== grade) return
    subjects.value = [...new Set(nextObjectives.map((objective) => objective.subject))]
  } catch (error: unknown) {
    if (generation === catalogGeneration) errorMessage.value = publicErrorMessage(error, '暂时无法读取学科目录，请稍后重试。')
  } finally {
    if (generation === catalogGeneration) catalogLoading.value = false
  }
}

async function selectSubject() {
  const profile = selectedProfile.value
  const grade = selectedGrade.value
  const subject = selectedSubject.value
  const generation = ++catalogGeneration
  clearPendingGenerationRequest()
  selectedObjectiveRevisionId.value = ''
  objectives.value = []
  resetCounts()
  if (!profile || !grade || !subject) {
    catalogLoading.value = false
    return
  }
  catalogLoading.value = true
  errorMessage.value = ''
  try {
    const nextObjectives = await fetchCurriculumObjectives($fetch, profile, grade, subject)
    if (
      generation === catalogGeneration
      && selectedProfile.value === profile
      && selectedGrade.value === grade
      && selectedSubject.value === subject
    ) objectives.value = nextObjectives
  } catch (error: unknown) {
    if (generation === catalogGeneration) errorMessage.value = publicErrorMessage(error, '暂时无法读取课程目标，请稍后重试。')
  } finally {
    if (generation === catalogGeneration) catalogLoading.value = false
  }
}

function selectObjective() {
  clearPendingGenerationRequest()
  resetCounts()
}

function resetCounts() {
  counts.value = {}
}

function updateCount(type: TeacherAiQuestionType, difficultyBand: TeacherAiDifficultyBand, amount: number) {
  if (!allowedTypes.value.includes(type)) return
  const current = counts.value[type]?.[difficultyBand] ?? 0
  const next = Math.max(0, current + amount)
  if (amount > 0 && requestedCount.value >= maximumCount.value) return
  if (next === current) return
  clearPendingGenerationRequest()
  counts.value = {
    ...counts.value,
    [type]: { ...counts.value[type], [difficultyBand]: next },
  }
}

watch(teacherConstraint, clearPendingGenerationRequest)

async function submit() {
  if (createDisabled.value || !selectedObjective.value) return
  submitting.value = true
  errorMessage.value = ''
  const input = generationInput()
  const idempotencyKey = idempotencyKeyFor(input)
  try {
    const principal = await fetchCurrentPrincipal($fetch)
    if (!principal.csrf_token) throw new MissingCsrfTokenError()
    const result = await createAiGenerationJob($fetch, principal.csrf_token, idempotencyKey, input)
    clearPendingGenerationRequest()
    await navigateTo(`/teacher/ai-questions?job=${encodeURIComponent(result.id)}`)
  } catch (error: unknown) {
    if (errorStatus(error) !== null) clearPendingGenerationRequest()
    errorMessage.value = publicErrorMessage(error, '暂时无法创建 AI 出题批次，请稍后重试。')
  } finally {
    submitting.value = false
  }
}

function generationInput(): CreateAiGenerationJobInput {
  const constraint = teacherConstraint.value.trim()
  return {
    curriculum_objective_revision_id: selectedObjective.value!.revision.id,
    items: requestedItems.value,
    requested_count: requestedCount.value,
    ...(constraint ? { teacher_constraint: constraint } : {}),
  }
}

function idempotencyKeyFor(input: CreateAiGenerationJobInput): string {
  const intent = JSON.stringify(input)
  if (pendingGenerationRequest.value?.intent === intent) {
    return pendingGenerationRequest.value.idempotencyKey
  }
  const idempotencyKey = crypto.randomUUID()
  pendingGenerationRequest.value = { intent, idempotencyKey }
  return idempotencyKey
}

function clearPendingGenerationRequest() {
  pendingGenerationRequest.value = null
}

function publicErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof MissingCsrfTokenError) return '登录会话已过期，请重新登录。'
  const status = errorStatus(error)
  if (status === 422) return '提交内容不符合要求，请检查后重试。'
  if (status === 409) return '生成请求状态已变更，请刷新后重试。'
  if (status === 429) return '请求过于频繁，请稍后重试。'
  if (status === 503) return 'AI 出题服务暂时不可用，请稍后重试。'
  if (error instanceof TypeError) return '网络连接异常，请检查网络后重试。'
  return fallback
}

function errorStatus(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) return null
  const candidate = error as { status?: unknown, statusCode?: unknown, response?: { status?: unknown } }
  for (const value of [candidate.statusCode, candidate.status, candidate.response?.status]) {
    if (typeof value === 'number') return value
  }
  return null
}

class MissingCsrfTokenError extends Error {}
</script>

<template>
  <section class="ai-generation-form" aria-labelledby="ai-generation-form-heading" :aria-busy="catalogLoading">
    <header class="teacher-page-heading">
      <div>
        <p class="eyebrow">教师端 · AI 出题</p>
        <h1 id="ai-generation-form-heading">创建 AI 出题批次</h1>
        <p class="teacher-page-heading__copy">先选择课程目标，再按获准题型安排本批次数量。</p>
      </div>
    </header>

    <p v-if="errorMessage" class="notice" role="alert">{{ errorMessage }}</p>
    <form class="stack card wide" @submit.prevent="submit">
      <label>课程方案
        <select v-model="selectedProfile" aria-label="课程方案" :disabled="submitting" @change="selectProfile">
          <option value="">请选择课程方案</option>
          <option v-for="profile in profiles" :key="profile.code" :value="profile.code">{{ profile.name }}</option>
        </select>
      </label>
      <label>年级
        <select v-model="selectedGrade" aria-label="年级" :disabled="!selectedProfile || submitting" @change="selectGrade">
          <option value="">请选择年级</option>
          <option v-for="grade in grades" :key="grade.internal_level" :value="grade.internal_level">{{ grade.external_label }}</option>
        </select>
      </label>
      <label>学科
        <select v-model="selectedSubject" aria-label="学科" :disabled="!selectedGrade || submitting" @change="selectSubject">
          <option value="">请选择学科</option>
          <option v-for="subject in subjects" :key="subject" :value="subject">{{ subject }}</option>
        </select>
      </label>
      <label>课程目标
        <select v-model="selectedObjectiveRevisionId" aria-label="课程目标" :disabled="!selectedSubject || submitting" @change="selectObjective">
          <option value="">请选择课程目标</option>
          <option v-for="objective in objectives" :key="objective.revision.id" :value="objective.revision.id">
            {{ objective.code }} · {{ objective.revision.text }}
          </option>
        </select>
      </label>

      <section v-if="selectedObjective" aria-labelledby="generation-options-heading">
        <h2 id="generation-options-heading">生成配置</h2>
        <p data-testid="difficulty-range">目标难度：{{ selectedObjective.revision.difficulty_min }} 至 {{ selectedObjective.revision.difficulty_max }}</p>
        <div class="ai-generation-form__counts">
          <fieldset v-for="type in allowedTypes" :key="type" class="ai-generation-form__type-group">
            <legend>{{ type }} 题</legend>
            <div v-for="difficultyBand in teacherAiDifficultyBands" :key="difficultyBand" class="ai-generation-form__count-control">
              <span>{{ difficultyBand }}</span>
              <button
                :aria-label="`减少 ${type} ${difficultyBand} 难度题数量`"
                :data-testid="`question-type-${type}-${difficultyBand}-decrement`"
                :disabled="submitting || !(counts[type]?.[difficultyBand] ?? 0)"
                type="button"
                @click="updateCount(type, difficultyBand, -1)"
              >−</button>
              <output :aria-label="`${type} ${difficultyBand} 难度题数量`">{{ counts[type]?.[difficultyBand] ?? 0 }}</output>
              <button
                :aria-label="`增加 ${type} ${difficultyBand} 难度题数量`"
                :data-testid="`question-type-${type}-${difficultyBand}-increment`"
                :disabled="submitting || requestedCount >= maximumCount"
                type="button"
                @click="updateCount(type, difficultyBand, 1)"
              >+</button>
            </div>
          </fieldset>
        </div>
        <p>本次共 {{ requestedCount }} 题，当前可生成上限 {{ maximumCount }} 题。</p>
      </section>

      <label>教师补充要求（可选）
        <textarea v-model="teacherConstraint" aria-label="教师补充要求" :disabled="submitting" maxlength="1000" rows="3" />
      </label>
      <button :disabled="createDisabled" data-testid="create-ai-generation-job" class="button primary" type="submit">
        {{ submitting ? '正在创建…' : '创建生成批次' }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.ai-generation-form__counts {
  display: grid;
  gap: 12px;
}

.ai-generation-form__type-group {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 12px;
}

.ai-generation-form__count-control {
  display: grid;
  grid-template-columns: minmax(88px, 1fr) auto minmax(32px, auto) auto;
  align-items: center;
  gap: 12px;
}

.ai-generation-form__count-control output {
  min-width: 2ch;
  text-align: center;
}

@media (max-width: 560px) {
  .ai-generation-form__count-control {
    grid-template-columns: 1fr auto auto auto;
  }
}
</style>
