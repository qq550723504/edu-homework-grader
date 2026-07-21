<template>
  <main class="shell teacher-page">
    <NuxtLink class="back" to="/">← 返回</NuxtLink><LogoutButton />
    <TeacherWorkbenchNav :active-module="activeModule" />
    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <TeacherOverview
      v-if="activeModule === 'overview'"
      :review-count="reviewCount"
      :completion-rate="completionRate"
      :published-assignments="publishedAssignments"
      @open-module="selectModule"
    />

    <TeacherQuestionWorkspace v-if="activeModule === 'questions'">
    <section class="card wide" aria-labelledby="create-question-heading">
      <span class="tag">题库</span>
      <h2 id="create-question-heading">创建草稿题目</h2>
      <form class="stack" @submit.prevent="submitQuestion">
        <label>题目标题<input v-model.trim="question.title" aria-label="题目标题" required maxlength="200"></label>
        <label>题干<textarea v-model.trim="question.prompt" aria-label="题干" required maxlength="10000" rows="3" /></label>
        <label>题型
          <select v-model="question.question_type" aria-label="题型" @change="applyRuleTemplate">
            <option v-for="type in questionTypes" :key="type.value" :value="type.value">{{ type.label }}</option>
          </select>
        </label>
        <label v-if="question.question_type === 'M1'">正确答案<input v-model.trim="question.expected" aria-label="正确答案" required inputmode="decimal"></label>
        <template v-else-if="isEnglishQuestion">
          <label><input v-model="advancedJsonMode" type="checkbox"> 高级 JSON 模式</label>
          <label v-if="advancedJsonMode">评分规则（JSON）<textarea v-model.trim="question.ruleJson" aria-label="评分规则" required rows="5" /></label>
          <template v-else-if="question.question_type === 'E1'">
            <label v-for="(_answer, index) in englishDraft.acceptedAnswers" :key="`e1-${index}`">可接受答案<input v-model.trim="englishDraft.acceptedAnswers[index]" aria-label="可接受答案"></label>
            <button class="button secondary" type="button" @click="englishDraft.acceptedAnswers.push('')">添加可接受答案</button>
          </template>
          <template v-else-if="question.question_type === 'E2'">
            <label>词元<input v-model.trim="englishDraft.lemma" aria-label="词元"></label>
            <label v-for="(_form, index) in englishDraft.acceptedForms" :key="`e2-${index}`">可接受词形<input v-model.trim="englishDraft.acceptedForms[index]" aria-label="可接受词形"></label>
            <button class="button secondary" type="button" @click="englishDraft.acceptedForms.push('')">添加可接受词形</button>
            <label>词性<input v-model.trim="englishDraft.constraints.partOfSpeech" aria-label="词性"></label>
            <label>时态<input v-model.trim="englishDraft.constraints.tense" aria-label="时态"></label>
            <label>单复数<input v-model.trim="englishDraft.constraints.number" aria-label="单复数"></label>
            <label>限定词<input v-model.trim="englishDraft.constraints.determiner" aria-label="限定词"></label>
          </template>
          <template v-else-if="question.question_type === 'E3'">
            <label v-for="(_answer, index) in englishDraft.acceptedAnswers" :key="`e3-${index}`">可接受答案<input v-model.trim="englishDraft.acceptedAnswers[index]" aria-label="可接受答案"></label>
            <label><input v-model="englishDraft.grammarFeedbackRequired" :value="true" type="radio"> 启用语法反馈</label>
            <label><input v-model="englishDraft.grammarFeedbackRequired" :value="false" type="radio"> 不启用语法反馈</label>
          </template>
          <template v-else>
            <section v-for="(point, index) in englishDraft.scoringPoints" :key="`e4-${index}`" class="stack">
              <h3>评分点 {{ index + 1 }}</h3>
              <label>评分点名称<input v-model.trim="point.id" aria-label="评分点名称"></label>
              <label v-for="(_phrase, phraseIndex) in point.evidencePhrases" :key="`e4-${index}-${phraseIndex}`">证据短语<input v-model.trim="point.evidencePhrases[phraseIndex]" aria-label="证据短语"></label>
              <button class="button secondary" type="button" @click="point.evidencePhrases.push('')">添加证据短语</button>
              <label>评分点分值<input v-model.number="point.score" aria-label="评分点分值" type="number" min="0" max="100" step="any"></label>
            </section>
            <button class="button secondary" type="button" @click="addScoringPoint">添加评分点</button>
            <label>语义阈值<input v-model.number="englishDraft.similarityThreshold" aria-label="语义阈值" type="number" min="0" max="1" step="0.01"></label>
          </template>
          <label>最高分<input v-model.number="englishDraft.maxScore" aria-label="最高分" type="number" min="0" max="100" step="any"></label>
          <p v-for="(error, field) in questionErrors" :key="field" class="notice" role="alert">{{ error }}</p>
        </template>
        <label v-else>评分规则（JSON）<textarea v-model.trim="question.ruleJson" aria-label="评分规则" required rows="5" /></label>
        <button class="button primary" :disabled="saving" type="submit">{{ saving ? '正在创建…' : '创建草稿题目' }}</button>
      </form>
    </section>

    <section class="stack" aria-labelledby="question-list-heading">
      <h2 id="question-list-heading">题库</h2>
      <div class="actions"><label>搜索题目<input v-model.trim="questionFilter.query" aria-label="搜索题目"></label><label>题型<select v-model="questionFilter.type" aria-label="筛选题型"><option value="">全部题型</option><option v-for="type in questionTypes" :key="type.value" :value="type.value">{{ type.label }}</option></select></label></div>
      <article v-for="version in filteredQuestionVersions" :key="version.id" class="assignment">
        <div><span class="subject">{{ version.question_type }} · {{ version.policy_version }}</span><h3>{{ version.title }}</h3><p>{{ version.status }} · {{ version.prompt }}</p></div>
        <button class="button secondary" type="button" @click="selectedVersionId = version.id">配置测试</button>
      </article>
      <p v-if="filteredQuestionVersions.length === 0" class="notice">当前筛选条件下暂无题目。</p>
    </section>

    <section v-if="selectedVersion" class="card wide" aria-labelledby="question-tests-heading">
      <span class="tag">发布门禁</span>
       <h2 id="question-tests-heading">{{ selectedVersion.title }}：测试与发布</h2>
       <div v-if="['E1', 'E2', 'E3', 'E4'].includes(selectedVersion.question_type)" class="actions">
         <button class="button secondary" :disabled="saving" type="button" @click="loadSuggestedTestCases">加载建议测试</button>
         <button v-for="template in suggestedTestCases" :key="template.category" class="button secondary" :disabled="saving" type="button" @click="applySuggestedTestCase(template)">使用 {{ template.category }} 模板</button>
         <button class="button secondary" :disabled="saving" type="button" @click="refreshTestCasePreview">刷新测试预览</button>
       </div>
      <form class="stack" @submit.prevent="submitTestCase">
        <label>用例类别<input v-model.trim="testCase.category" aria-label="用例类别" required placeholder="correct / incorrect / empty / boundary"></label>
        <label>学生答案（JSON）<textarea v-model.trim="testCase.answerJson" aria-label="学生答案 JSON" required rows="3" /></label>
        <label>预期判定<input v-model.trim="testCase.expectedDecision" aria-label="预期判定" required></label>
        <label>预期分数<input v-model.number="testCase.expectedScore" aria-label="预期分数" required type="number" min="0" step="any"></label>
        <label>预期证据（JSON）<textarea v-model.trim="testCase.expectedEvidenceJson" aria-label="预期证据 JSON" required rows="4" /></label>
        <button class="button secondary" :disabled="saving" type="submit">添加测试用例</button>
      </form>
      <div class="actions"><button class="button primary" :disabled="saving" type="button" @click="runTests">运行测试</button><button class="button secondary" :disabled="saving || latestTestRun?.status !== 'passed'" type="button" @click="publishSelectedVersion">发布题目版本</button></div>
      <p v-if="latestTestRun" class="notice">最近测试：{{ latestTestRun.status }}{{ latestTestRun.failure_summary ? ` · ${latestTestRun.failure_summary}` : '' }}</p>
      <article v-for="caseRun in latestTestRun?.case_runs ?? []" :key="caseRun.category" class="assignment"><div><span class="subject">{{ caseRun.category }}</span><h3>{{ caseRun.passed ? '通过' : '未通过' }} · {{ caseRun.decision }} · {{ caseRun.score }}</h3><p v-if="caseRun.error_detail">{{ caseRun.error_detail }}</p><pre v-else>{{ JSON.stringify(caseRun.evidence, null, 2) }}</pre></div></article>
    </section>
    </TeacherQuestionWorkspace>

    <TeacherAssignmentWorkspace v-if="activeModule === 'assignments'">
    <section class="card wide" aria-labelledby="create-assignment-heading">
      <span class="tag">作业</span>
      <h2 id="create-assignment-heading">创建作业草稿</h2>
      <form class="stack" @submit.prevent="submitAssignment">
        <label>作业标题<input v-model.trim="assignmentForm.title" aria-label="作业标题" required maxlength="200"></label>
        <label>班级<select v-model="assignmentForm.classId" aria-label="班级" :disabled="saving || Boolean(pendingAssignmentId)" required><option disabled value="">选择班级</option><option v-for="classroom in workspace.classes" :key="classroom.id" :value="classroom.id">{{ classroom.code }} · {{ classroom.name }}</option></select></label>
        <label>作业学科<select v-model="assignmentForm.subject" aria-label="作业学科" :disabled="saving || Boolean(pendingAssignmentId)"><option value="mathematics">数学</option><option value="english">英语</option></select></label>
        <label>截止时间<input v-model="assignmentForm.dueAt" aria-label="截止时间" required type="datetime-local"></label>
        <label><input v-model="assignmentForm.allowLate" type="checkbox"> 允许迟交</label>
        <section class="stack" aria-labelledby="available-questions-heading">
          <h3 id="available-questions-heading">可添加的已发布题目</h3>
          <article v-for="version in availableAssignmentQuestions" :key="version.id" class="assignment">
            <div><span class="subject">{{ version.question_type }} · {{ version.policy_version }} · {{ version.max_score }} 分</span><h4>{{ version.title }}</h4><p>{{ version.prompt }}</p></div>
            <button class="button secondary" :aria-label="`添加题目 ${version.question_type}`" :disabled="saving || selectedAssignmentQuestions.some((item) => item.id === version.id)" type="button" @click="addAssignmentQuestion(version)">添加</button>
          </article>
          <p v-if="availableAssignmentQuestions.length === 0" class="notice">当前学科没有可添加的已发布题目。</p>
        </section>
        <section class="stack" aria-labelledby="assignment-composition-heading">
          <h3 id="assignment-composition-heading">作业题目编排</h3>
          <p class="notice">共 {{ assignmentComposition.count }} 题，{{ assignmentComposition.totalScore }} 分 · {{ Object.entries(assignmentComposition.types).map(([type, count]) => `${type} ${count} 题`).join('，') || '尚未选择题目' }}</p>
          <article v-for="(version, index) in selectedAssignmentQuestions" :key="version.id" class="assignment">
            <div><span class="subject">第 {{ index + 1 }} 题 · {{ version.question_type }} · {{ version.max_score }} 分</span><h4>{{ version.title }}</h4><p>{{ version.prompt }}</p></div>
            <div class="actions"><button class="button secondary" :aria-label="`上移 ${version.question_type}`" :disabled="saving || index === 0" type="button" @click="moveAssignmentQuestion(index, -1)">上移</button><button class="button secondary" :aria-label="`下移 ${version.question_type}`" :disabled="saving || index === selectedAssignmentQuestions.length - 1" type="button" @click="moveAssignmentQuestion(index, 1)">下移</button><button class="button secondary" :aria-label="`移除 ${version.question_type}`" :disabled="saving" type="button" @click="removeAssignmentQuestion(version.id)">移除</button></div>
          </article>
          <p v-if="selectedAssignmentQuestions.length === 0" class="notice">请至少添加一道与作业学科一致的已发布题目。</p>
        </section>
        <section v-if="selectedAssignmentQuestions.length" class="stack" aria-labelledby="student-preview-heading">
          <h3 id="student-preview-heading">学生预览</h3>
          <ol><li v-for="version in selectedAssignmentQuestions" :key="version.id"><strong>{{ version.title }}</strong> · {{ version.prompt }}</li></ol>
        </section>
        <button class="button primary" :disabled="saving" type="submit">{{ pendingAssignmentId ? '保存编排' : '创建作业草稿' }}</button>
      </form>
      <div v-if="pendingAssignmentId" class="actions"><button class="button secondary" :disabled="saving" type="button" @click="publishPendingAssignment">发布作业</button></div>
    </section>

    <section class="stack" aria-labelledby="assignment-list-heading">
      <h2 id="assignment-list-heading">作业</h2>
      <article v-for="assignment in workspace.assignments" :key="assignment.id" class="assignment">
        <div><span class="subject">{{ assignment.subject }}</span><h3>{{ assignment.title }}</h3><p>{{ assignment.class_name }} · 已交 {{ assignment.submitted_count }}/{{ assignment.student_count }} · {{ assignment.status }}</p></div>
      </article>
      <p v-if="workspace.assignments.length === 0" class="notice">暂无作业。</p>
    </section>
    </TeacherAssignmentWorkspace>

    <section v-if="activeModule === 'roster'" class="card wide" aria-labelledby="roster-heading">
      <span class="tag">班级名册</span>
      <h2 id="roster-heading">创建班级与录入学生</h2>
      <form class="stack" @submit.prevent="submitRosterClass">
        <label>班级代码<input v-model.trim="rosterClassDraft.code" required maxlength="100" placeholder="例如：7A"></label>
        <label>班级名称<input v-model.trim="rosterClassDraft.name" required maxlength="200" placeholder="例如：七年级 A 班"></label>
        <button class="button primary" :disabled="saving" type="submit">创建班级</button>
      </form>
      <div v-if="rosterClasses.length" class="stack">
        <h3>我的班级</h3>
        <button v-for="classroom in rosterClasses" :key="classroom.id" class="button secondary" type="button" @click="selectedRosterClassId = classroom.id">
          {{ classroom.code }} · {{ classroom.name }} · {{ classroom.student_count }} 名学生
        </button>
      </div>
      <form v-if="selectedRosterClassId" class="stack" @submit.prevent="submitRosterStudent">
        <h3>录入学生</h3>
        <label>学号<input v-model.trim="rosterStudentDraft.school_id" required maxlength="100"></label>
        <label>学生姓名<input v-model.trim="rosterStudentDraft.display_name" required maxlength="200"></label>
        <label><input v-model="rosterStudentDraft.under_14" type="checkbox"> 学生未满 14 岁</label>
        <template v-if="guardianConsentFieldsRequired(rosterStudentDraft.under_14)">
          <label>监护人同意状态<select v-model="rosterStudentDraft.guardian_consent_status"><option value="pending">待确认</option><option value="granted">已同意</option><option value="withdrawn">已撤回</option></select></label>
          <label v-if="rosterStudentDraft.guardian_consent_status === 'granted'">通知版本<input v-model.trim="rosterStudentDraft.guardian_consent_notice_version" required maxlength="50"></label>
          <label v-if="rosterStudentDraft.guardian_consent_status === 'granted'">同意凭据引用<input v-model.trim="rosterStudentDraft.guardian_consent_evidence_reference" required maxlength="100"></label>
        </template>
        <button class="button primary" :disabled="saving" type="submit">添加学生</button>
      </form>
      <form v-if="selectedRosterClassId" class="stack" @submit.prevent="submitRosterImport">
        <h3>导入 CSV 名册</h3>
        <label>CSV 文件<input accept=".csv,text/csv" required type="file" @change="selectRosterFile"></label>
        <button class="button secondary" :disabled="saving" type="submit">导入 CSV</button>
      </form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { fetchCurrentPrincipal } from '../../lib/student-api'
import { createAssignment, createQuestion, createTeacherRosterClass, createTeacherRosterStudent, createTestCase, fetchQuestionPolicyCatalog, fetchQuestionTestCaseTemplates, fetchTeacherRosterClasses, fetchTeacherWorkspace, importTeacherRoster, previewQuestionTestCase, publishAssignment, publishQuestionVersion, runQuestionTests, updateAssignment, type CreateQuestionInput, type QuestionPolicyCatalogEntry, type QuestionTestCaseTemplate, type QuestionTestRun, type TeacherAssignment, type TeacherQuestionVersion, type TeacherRosterClass } from '../../lib/teacher-api'
import { addQuestionToComposition, availableQuestionsForSubject, compositionSummary, moveQuestion, removeQuestion, type AssignmentSubject } from '../../lib/assignment-composition'
import { buildEnglishQuestionRule, defaultEnglishDraft, fieldForPolicyError, type EnglishQuestionType } from '../../lib/english-question-authoring'
import { teacherModules, type TeacherModule } from '../../lib/teacher-workbench'
import { clearGuardianConsentEvidence, guardianConsentFieldsRequired, teacherErrorMessage } from '../../lib/teacher-workflow'

const workspace = ref<{ classes: Array<{ id: string; code: string; name: string }>; questionVersions: TeacherQuestionVersion[]; assignments: TeacherAssignment[]; reviewMetrics: Record<string, unknown>; reviewTasks: Array<{ id: string }> }>({ classes: [], questionVersions: [], assignments: [], reviewMetrics: {}, reviewTasks: [] })
const rosterClasses = ref<TeacherRosterClass[]>([])
const selectedRosterClassId = ref('')
const rosterFile = ref<File | null>(null)
const rosterClassDraft = reactive({ code: '', name: '' })
const rosterStudentDraft = reactive({ school_id: '', display_name: '', under_14: false, guardian_consent_status: 'not_required' as 'not_required' | 'pending' | 'granted' | 'withdrawn', guardian_consent_notice_version: '', guardian_consent_evidence_reference: '' })
const message = ref('')
const saving = ref(false)
const selectedVersionId = ref<string | null>(null)
const latestTestRun = ref<QuestionTestRun | null>(null)
const pendingAssignmentId = ref<string | null>(null)
const questionPolicies = ref<QuestionPolicyCatalogEntry[]>([])
const englishDraft = reactive(defaultEnglishDraft('E1'))
const advancedJsonMode = ref(false)
const questionErrors = ref<Record<string, string>>({})
const suggestedTestCases = ref<QuestionTestCaseTemplate[]>([])
const activeModule = ref<TeacherModule>('overview')
const route = useRoute()

function moduleFromHash(hash: string): TeacherModule {
  const requestedModule = hash.slice(1)
  return teacherModules.some((module) => module.id === requestedModule)
    ? requestedModule as TeacherModule
    : 'overview'
}

function syncModuleFromHash(hash = route.hash) {
  activeModule.value = moduleFromHash(hash)
}
const questionTypes = [
  { value: 'M1', label: 'M1 数值题', policy: '1', rule: '{"expected": 0}' },
  { value: 'M2', label: 'M2 表达式题', policy: '2', rule: '{"expected": ["Add", "x", 1], "variables": ["x"], "required_form": "expanded", "max_score": 1}' },
  { value: 'E1', label: 'E1 精确匹配', policy: '', rule: '' },
  { value: 'E2', label: 'E2 受限填空', policy: '', rule: '' },
  { value: 'E3', label: 'E3 句子题', policy: '', rule: '' },
  { value: 'E4', label: 'E4 阅读简答辅助', policy: '', rule: '' },
]
const question = reactive({ title: '', prompt: '', question_type: 'M1', expected: '', ruleJson: questionTypes[0].rule })
const questionFilter = reactive({ query: '', type: '' })
const testCase = reactive({ category: 'correct', answerJson: '{"format":"text-v1","text":"5"}', expectedDecision: 'auto_accepted', expectedScore: 1, expectedEvidenceJson: '{}' })
const assignmentForm = reactive({ title: '', classId: '', subject: 'mathematics' as AssignmentSubject, dueAt: '', allowLate: false })
const selectedAssignmentQuestions = ref<TeacherQuestionVersion[]>([])
const selectedVersion = computed(() => workspace.value.questionVersions.find((version) => version.id === selectedVersionId.value))
const filteredQuestionVersions = computed(() => workspace.value.questionVersions.filter((version) => {
  const query = questionFilter.query.toLocaleLowerCase()
  return (!query || `${version.title} ${version.prompt}`.toLocaleLowerCase().includes(query)) && (!questionFilter.type || version.question_type === questionFilter.type)
}))
const availableAssignmentQuestions = computed(() => availableQuestionsForSubject(workspace.value.questionVersions, assignmentForm.subject))
const assignmentComposition = computed(() => compositionSummary(selectedAssignmentQuestions.value))
const isEnglishQuestion = computed(() => ['E1', 'E2', 'E3', 'E4'].includes(question.question_type))
const reviewCount = computed(() => workspace.value.reviewTasks.length)
const publishedAssignments = computed(() => workspace.value.assignments.filter((assignment) => assignment.status === 'published').length)
const completionRate = computed(() => {
  const assigned = workspace.value.assignments.reduce((total, assignment) => total + assignment.student_count, 0)
  const submitted = workspace.value.assignments.reduce((total, assignment) => total + assignment.submitted_count, 0)
  return assigned === 0 ? 0 : Math.round((submitted / assigned) * 100)
})

function selectModule(module: TeacherModule) {
  if (module === 'reviews') return navigateTo('/teacher/reviews')
  if (module === 'requests') return navigateTo('/teacher/appeals')
  activeModule.value = module
  return navigateTo({ hash: `#${module}` })
}

async function loadWorkspace() {
  const [nextWorkspace, nextRosterClasses, nextQuestionPolicies] = await Promise.all([
    fetchTeacherWorkspace($fetch),
    fetchTeacherRosterClasses($fetch),
    fetchQuestionPolicyCatalog($fetch),
  ])
  workspace.value = nextWorkspace
  rosterClasses.value = nextRosterClasses
  questionPolicies.value = nextQuestionPolicies
  if (selectedRosterClassId.value && !nextRosterClasses.some((item) => item.id === selectedRosterClassId.value)) selectedRosterClassId.value = ''
}

function applyRuleTemplate() {
  const template = questionTypes.find((entry) => entry.value === question.question_type)!
  questionErrors.value = {}
  advancedJsonMode.value = false
  if (isEnglishQuestion.value) {
    Object.assign(englishDraft, defaultEnglishDraft(question.question_type as EnglishQuestionType))
    if (question.question_type === 'E4') addScoringPoint()
    question.ruleJson = ''
    return
  }
  question.ruleJson = template.rule
}

function addScoringPoint() {
  englishDraft.scoringPoints.push({ id: '', evidencePhrases: [''], score: 1 })
}

function questionInput(): CreateQuestionInput {
  const template = questionTypes.find((entry) => entry.value === question.question_type)!
  questionErrors.value = {}
  const rule = question.question_type === 'M1'
    ? { expected: Number(question.expected) }
    : isEnglishQuestion.value && !advancedJsonMode.value
      ? guidedEnglishRule()
      : JSON.parse(question.ruleJson) as Record<string, unknown>
  if (question.question_type === 'M1' && !Number.isFinite(rule.expected)) {
    throw new Error('正确答案必须是有限数字。')
  }
  const policyVersion = isEnglishQuestion.value
    ? questionPolicies.value.find((entry) => entry.question_type === question.question_type)?.policy_version
    : template.policy
  if (!policyVersion) throw new Error(`当前题型尚未开放：${question.question_type}`)
  return { title: question.title, prompt: question.prompt, question_type: question.question_type, policy_version: policyVersion, rule }
}

function guidedEnglishRule(): Record<string, unknown> {
  const result = buildEnglishQuestionRule(question.question_type as EnglishQuestionType, englishDraft)
  questionErrors.value = result.errors
  if (!result.rule) throw new Error('请修正题目规则中的错误。')
  return result.rule
}

function applyQuestionPolicyErrors(error: unknown): boolean {
  if (!isEnglishQuestion.value || typeof error !== 'object' || error === null || !('data' in error)) return false
  const detail = (error as { data?: { detail?: { errors?: unknown } } }).data?.detail
  if (!detail || !Array.isArray(detail.errors)) return false
  questionErrors.value = Object.fromEntries(detail.errors.flatMap((item) => {
    if (typeof item !== 'object' || item === null || !('path' in item) || !('message' in item)) return []
    const path = typeof item.path === 'string' ? fieldForPolicyError(item.path) : null
    const message = typeof item.message === 'string' ? item.message : null
    return path && message ? [[path, message]] : []
  }))
  return Object.keys(questionErrors.value).length > 0
}

async function submitQuestion() {
  saving.value = true
  message.value = ''
  try {
    const principal = await fetchCurrentPrincipal($fetch)
    if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。')
    const created = await createQuestion($fetch, principal.csrf_token, questionInput())
    selectedVersionId.value = created.id
    message.value = '草稿题目已创建'
    question.title = ''
    question.prompt = ''
    question.expected = ''
    await loadWorkspace()
  } catch (error: unknown) {
    message.value = applyQuestionPolicyErrors(error)
      ? '请修正题目规则中的错误。'
      : error instanceof Error ? error.message : '创建题目失败，请稍后重试。'
  } finally {
    saving.value = false
  }
}

async function csrfToken(): Promise<string> {
  const principal = await fetchCurrentPrincipal($fetch)
  if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。')
  return principal.csrf_token
}

watch(() => rosterStudentDraft.under_14, (under14) => {
  rosterStudentDraft.guardian_consent_status = under14 ? 'pending' : 'not_required'
})

watch(() => rosterStudentDraft.guardian_consent_status, (status) => {
  const evidence = clearGuardianConsentEvidence(
    status,
    rosterStudentDraft.guardian_consent_notice_version,
    rosterStudentDraft.guardian_consent_evidence_reference,
  )
  rosterStudentDraft.guardian_consent_notice_version = evidence.noticeVersion
  rosterStudentDraft.guardian_consent_evidence_reference = evidence.evidenceReference
})

watch(() => selectedVersionId.value, () => {
  suggestedTestCases.value = []
  latestTestRun.value = null
})

watch(() => assignmentForm.subject, () => {
  selectedAssignmentQuestions.value = []
})

async function submitRosterClass() {
  saving.value = true
  try {
    const classroom = await createTeacherRosterClass($fetch, await csrfToken(), rosterClassDraft)
    rosterClassDraft.code = ''
    rosterClassDraft.name = ''
    selectedRosterClassId.value = classroom.id
    message.value = '班级已创建。'
    await loadWorkspace()
  } catch (error: unknown) { message.value = teacherErrorMessage(error) }
  finally { saving.value = false }
}

async function submitRosterStudent() {
  if (!selectedRosterClassId.value) return
  saving.value = true
  try {
    await createTeacherRosterStudent($fetch, await csrfToken(), selectedRosterClassId.value, rosterStudentDraft)
    rosterStudentDraft.school_id = ''
    rosterStudentDraft.display_name = ''
    message.value = '学生已录入。'
    await loadWorkspace()
  } catch (error: unknown) { message.value = teacherErrorMessage(error) }
  finally { saving.value = false }
}

function selectRosterFile(event: Event) {
  rosterFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submitRosterImport() {
  if (!selectedRosterClassId.value || !rosterFile.value) return
  saving.value = true
  try {
    const result = await importTeacherRoster($fetch, await csrfToken(), selectedRosterClassId.value, rosterFile.value)
    rosterFile.value = null
    message.value = `已导入 ${result.imported} 名学生。`
    await loadWorkspace()
  } catch (error: unknown) { message.value = teacherErrorMessage(error) }
  finally { saving.value = false }
}

async function submitTestCase() {
  if (!selectedVersionId.value) return
  saving.value = true
  message.value = ''
  try {
    await createTestCase($fetch, await csrfToken(), selectedVersionId.value, {
      category: testCase.category,
      answer: JSON.parse(testCase.answerJson) as Record<string, unknown>,
      expected_decision: testCase.expectedDecision,
      expected_score: Number(testCase.expectedScore),
      expected_evidence: JSON.parse(testCase.expectedEvidenceJson) as Record<string, unknown>,
    })
    message.value = '测试用例已添加'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '添加测试用例失败。' }
  finally { saving.value = false }
}

async function runTests() {
  if (!selectedVersionId.value) return
  saving.value = true
  message.value = ''
  try {
    latestTestRun.value = await runQuestionTests($fetch, await csrfToken(), selectedVersionId.value)
    message.value = latestTestRun.value.status === 'passed' ? '全部测试通过，可以发布。' : '测试未通过，请检查逐条结果。'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '运行测试失败。' }
  finally { saving.value = false }
}

async function publishSelectedVersion() {
  if (!selectedVersionId.value) return
  saving.value = true
  try {
    await publishQuestionVersion($fetch, await csrfToken(), selectedVersionId.value)
    message.value = '题目版本已发布'
    await loadWorkspace()
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '发布题目失败。' }
  finally { saving.value = false }
}

async function submitAssignment() {
  if (!selectedAssignmentQuestions.value.length) {
    message.value = '请至少添加一道题目后再保存作业。'
    return
  }
  saving.value = true
  message.value = ''
  try {
    const composition = {
      title: assignmentForm.title,
      due_at: new Date(assignmentForm.dueAt).toISOString(),
      submission_rule: { allow_late: assignmentForm.allowLate },
      question_version_ids: selectedAssignmentQuestions.value.map((version) => version.id),
    }
    if (pendingAssignmentId.value) {
      await updateAssignment($fetch, await csrfToken(), pendingAssignmentId.value, composition)
      message.value = '作业编排已保存，请确认后发布。'
    } else {
      const assignment = await createAssignment($fetch, await csrfToken(), {
        ...composition,
        class_id: assignmentForm.classId,
        subject: assignmentForm.subject,
      })
      pendingAssignmentId.value = assignment.id
      message.value = '作业草稿已创建，请确认后发布。'
    }
    await loadWorkspace()
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '创建作业失败。' }
  finally { saving.value = false }
}

async function loadSuggestedTestCases() {
  if (!selectedVersionId.value) return
  saving.value = true
  try {
    suggestedTestCases.value = await fetchQuestionTestCaseTemplates($fetch, selectedVersionId.value)
    if (suggestedTestCases.value[0]) await applySuggestedTestCase(suggestedTestCases.value[0])
    message.value = '已加载可编辑的建议测试。'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '加载建议测试失败。' }
  finally { saving.value = false }
}

async function applySuggestedTestCase(template: QuestionTestCaseTemplate) {
  testCase.category = template.category
  testCase.answerJson = JSON.stringify(template.answer)
  await refreshTestCasePreview()
}

async function refreshTestCasePreview() {
  if (!selectedVersionId.value) return
  saving.value = true
  try {
    const preview = await previewQuestionTestCase(
      $fetch,
      await csrfToken(),
      selectedVersionId.value,
      JSON.parse(testCase.answerJson) as Record<string, unknown>,
    )
    testCase.expectedDecision = preview.decision
    testCase.expectedScore = preview.score
    testCase.expectedEvidenceJson = JSON.stringify(preview.evidence)
    message.value = '已刷新测试预览，可继续编辑后添加。'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '刷新测试预览失败。' }
  finally { saving.value = false }
}

function addAssignmentQuestion(version: TeacherQuestionVersion) {
  selectedAssignmentQuestions.value = addQuestionToComposition(
    selectedAssignmentQuestions.value, version, assignmentForm.subject,
  )
}

function moveAssignmentQuestion(index: number, offset: number) {
  selectedAssignmentQuestions.value = moveQuestion(selectedAssignmentQuestions.value, index, offset)
}

function removeAssignmentQuestion(questionVersionId: string) {
  selectedAssignmentQuestions.value = removeQuestion(selectedAssignmentQuestions.value, questionVersionId)
}

async function publishPendingAssignment() {
  if (!pendingAssignmentId.value) return
  saving.value = true
  try {
    await publishAssignment($fetch, await csrfToken(), pendingAssignmentId.value)
    pendingAssignmentId.value = null
    message.value = '作业已发布'
    await loadWorkspace()
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '发布作业失败。' }
  finally { saving.value = false }
}

watch(() => route.hash, syncModuleFromHash, { immediate: true })

onMounted(async () => {
  try { await loadWorkspace() }
  catch { message.value = '暂时无法读取教师工作台。' }
})
</script>
