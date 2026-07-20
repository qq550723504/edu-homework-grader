<template>
  <main class="shell">
    <NuxtLink class="back" to="/">← 返回</NuxtLink><LogoutButton />
    <p class="eyebrow">教师端</p>
    <h1>教学工作台</h1>
    <p v-if="message" class="notice" role="status">{{ message }}</p>

    <section class="metrics" aria-label="工作台指标">
      <article class="metric"><strong>{{ reviewCount }}</strong><span>待复核答案</span></article>
      <article class="metric"><strong>{{ completionRate }}%</strong><span>作业完成率</span></article>
      <article class="metric"><strong>{{ publishedAssignments }}</strong><span>已发布作业</span></article>
    </section>
    <div class="actions"><NuxtLink class="button secondary" to="/teacher/reviews">处理复核队列（{{ reviewCount }}）</NuxtLink><NuxtLink class="button secondary" to="/teacher/appeals">处理学生申诉</NuxtLink></div>

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

    <section class="card wide" aria-labelledby="create-assignment-heading">
      <span class="tag">作业</span>
      <h2 id="create-assignment-heading">创建作业草稿</h2>
      <form class="stack" @submit.prevent="submitAssignment">
        <label>作业标题<input v-model.trim="assignmentForm.title" aria-label="作业标题" required maxlength="200"></label>
        <label>班级<select v-model="assignmentForm.classId" aria-label="班级" required><option disabled value="">选择班级</option><option v-for="classroom in workspace.classes" :key="classroom.id" :value="classroom.id">{{ classroom.code }} · {{ classroom.name }}</option></select></label>
        <label>题目版本<select v-model="assignmentForm.questionVersionId" aria-label="题目版本" required><option disabled value="">选择已发布题目</option><option v-for="version in publishedQuestionVersions" :key="version.id" :value="version.id">{{ version.title }} · {{ version.question_type }}</option></select></label>
        <label>截止时间<input v-model="assignmentForm.dueAt" aria-label="截止时间" required type="datetime-local"></label>
        <label><input v-model="assignmentForm.allowLate" type="checkbox"> 允许迟交</label>
        <button class="button primary" :disabled="saving" type="submit">创建作业草稿</button>
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
  </main>
</template>

<script setup lang="ts">
import { fetchCurrentPrincipal } from '../../lib/student-api'
import { addAssignmentItem, createAssignment, createQuestion, createTestCase, fetchTeacherWorkspace, publishAssignment, publishQuestionVersion, runQuestionTests, type CreateQuestionInput, type QuestionTestRun, type TeacherAssignment, type TeacherQuestionVersion } from '../../lib/teacher-api'

const workspace = ref<{ classes: Array<{ id: string; code: string; name: string }>; questionVersions: TeacherQuestionVersion[]; assignments: TeacherAssignment[]; reviewMetrics: Record<string, unknown>; reviewTasks: Array<{ id: string }> }>({ classes: [], questionVersions: [], assignments: [], reviewMetrics: {}, reviewTasks: [] })
const message = ref('')
const saving = ref(false)
const selectedVersionId = ref<string | null>(null)
const latestTestRun = ref<QuestionTestRun | null>(null)
const pendingAssignmentId = ref<string | null>(null)
const questionTypes = [
  { value: 'M1', label: 'M1 数值题', policy: '1', rule: '{"expected": 0}' },
  { value: 'M2', label: 'M2 表达式题', policy: '2', rule: '{"expected": ["Add", "x", 1], "variables": ["x"], "required_form": "expanded", "max_score": 1}' },
  { value: 'E1', label: 'E1 精确匹配', policy: '2', rule: '{"accepted_answers": []}' },
  { value: 'E2', label: 'E2 受限填空', policy: '1', rule: '{"accepted_forms": []}' },
  { value: 'E3', label: 'E3 句子题', policy: '1', rule: '{}' },
  { value: 'E4', label: 'E4 阅读简答辅助', policy: '1', rule: '{}' },
]
const question = reactive({ title: '', prompt: '', question_type: 'M1', expected: '', ruleJson: questionTypes[0].rule })
const questionFilter = reactive({ query: '', type: '' })
const testCase = reactive({ category: 'correct', answerJson: '{"format":"text-v1","text":"5"}', expectedDecision: 'auto_accepted', expectedScore: 1, expectedEvidenceJson: '{}' })
const assignmentForm = reactive({ title: '', classId: '', questionVersionId: '', dueAt: '', allowLate: false })
const selectedVersion = computed(() => workspace.value.questionVersions.find((version) => version.id === selectedVersionId.value))
const filteredQuestionVersions = computed(() => workspace.value.questionVersions.filter((version) => {
  const query = questionFilter.query.toLocaleLowerCase()
  return (!query || `${version.title} ${version.prompt}`.toLocaleLowerCase().includes(query)) && (!questionFilter.type || version.question_type === questionFilter.type)
}))
const publishedQuestionVersions = computed(() => workspace.value.questionVersions.filter((version) => version.status === 'published'))
const reviewCount = computed(() => workspace.value.reviewTasks.length)
const publishedAssignments = computed(() => workspace.value.assignments.filter((assignment) => assignment.status === 'published').length)
const completionRate = computed(() => {
  const assigned = workspace.value.assignments.reduce((total, assignment) => total + assignment.student_count, 0)
  const submitted = workspace.value.assignments.reduce((total, assignment) => total + assignment.submitted_count, 0)
  return assigned === 0 ? 0 : Math.round((submitted / assigned) * 100)
})

async function loadWorkspace() {
  workspace.value = await fetchTeacherWorkspace($fetch)
}

function applyRuleTemplate() {
  const template = questionTypes.find((entry) => entry.value === question.question_type)!
  question.ruleJson = template.rule
}

function questionInput(): CreateQuestionInput {
  const template = questionTypes.find((entry) => entry.value === question.question_type)!
  const rule = question.question_type === 'M1'
    ? { expected: Number(question.expected) }
    : JSON.parse(question.ruleJson) as Record<string, unknown>
  if (question.question_type === 'M1' && !Number.isFinite(rule.expected)) {
    throw new Error('正确答案必须是有限数字。')
  }
  return { title: question.title, prompt: question.prompt, question_type: question.question_type, policy_version: template.policy, rule }
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
    message.value = error instanceof Error ? error.message : '创建题目失败，请稍后重试。'
  } finally {
    saving.value = false
  }
}

async function csrfToken(): Promise<string> {
  const principal = await fetchCurrentPrincipal($fetch)
  if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。')
  return principal.csrf_token
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
  saving.value = true
  message.value = ''
  try {
    const assignment = await createAssignment($fetch, await csrfToken(), {
      class_id: assignmentForm.classId,
      title: assignmentForm.title,
      subject: 'mathematics',
      due_at: new Date(assignmentForm.dueAt).toISOString(),
      submission_rule: { allow_late: assignmentForm.allowLate },
    })
    await addAssignmentItem($fetch, await csrfToken(), assignment.id, { question_version_id: assignmentForm.questionVersionId, position: 1 })
    pendingAssignmentId.value = assignment.id
    message.value = '作业草稿已创建，请确认后发布。'
    await loadWorkspace()
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '创建作业失败。' }
  finally { saving.value = false }
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

onMounted(async () => {
  try { await loadWorkspace() }
  catch { message.value = '暂时无法读取教师工作台。' }
})
</script>
