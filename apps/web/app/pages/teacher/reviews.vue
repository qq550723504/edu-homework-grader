<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/teacher">← 返回教师工作台</NuxtLink><LogoutButton />
    <p class="eyebrow">教师端 · 复核</p>
    <h1>复核队列</h1>
    <p v-if="message" class="notice" role="status">{{ message }}</p>

    <section class="card wide">
      <h2>筛选待处理事项</h2>
      <form class="stack" @submit.prevent="loadTasks">
        <label>班级<select v-model="filters.class_id" aria-label="复核班级"><option value="">全部班级</option><option v-for="classroom in workspace.classes" :key="classroom.id" :value="classroom.id">{{ classroom.code }} · {{ classroom.name }}</option></select></label>
        <label>作业<select v-model="filters.assignment_id" aria-label="复核作业"><option value="">全部作业</option><option v-for="assignment in workspace.assignments" :key="assignment.id" :value="assignment.id">{{ assignment.title }}</option></select></label>
        <label>学科<select v-model="filters.subject" aria-label="复核学科"><option value="">全部学科</option><option value="mathematics">数学</option><option value="english">英语</option></select></label>
        <label>题型<select v-model="filters.question_type" aria-label="复核题型"><option value="">全部题型</option><option v-for="type in questionTypes" :key="type" :value="type">{{ type }}</option></select></label>
        <label>原因<select v-model="filters.reason" aria-label="复核原因"><option value="">需人工复核</option><option value="auto_confirmation">确定性答案待确认</option><option value="needs_review">需人工复核</option></select></label>
        <button class="button secondary" :disabled="loading" type="submit">{{ loading ? '正在加载…' : '应用筛选' }}</button>
      </form>
    </section>

    <section class="stack" aria-labelledby="review-list-heading">
      <h2 id="review-list-heading">待复核答案</h2>
      <article v-for="task in tasks" :key="task.id" class="assignment">
        <div><span class="subject">{{ task.question_type }} · {{ task.reason }}</span><h3>尝试 {{ task.attempt_id.slice(0, 8) }}</h3><p>{{ task.submitted_late ? '迟交' : '按时提交' }} · 版本 {{ task.version }}</p></div>
        <div class="actions"><input v-if="task.reason === 'auto_confirmation'" v-model="batchTaskIds" :aria-label="`批量确认 ${task.id}`" type="checkbox" :value="task.id"><button class="button secondary" type="button" @click="selectTask(task)">查看证据</button></div>
      </article>
      <p v-if="tasks.length === 0" class="notice">当前筛选条件下没有待处理复核。</p>
      <button v-if="batchTaskIds.length" class="button primary" :disabled="saving" type="button" @click="confirmBatch">批量确认 {{ batchTaskIds.length }} 个确定性答案</button>
    </section>

    <section v-if="activeTask && detail" class="card wide" aria-labelledby="review-detail-heading">
      <span class="tag">{{ detail.reason }}</span>
      <h2 id="review-detail-heading">复核详情</h2>
      <p>任务状态：{{ detail.status }} · 批改版本：{{ detail.version }}</p>
      <h3>学生答案</h3><pre>{{ pretty(detail.answer) }}</pre>
      <h3>规则快照</h3><pre>{{ pretty(detail.rule_snapshot) }}</pre>
      <h3>评分结果</h3><pre>{{ pretty(detail.grading) }}</pre>
      <h3>评分点与信号</h3><pre>{{ pretty(detail.signals) }}</pre>
      <h3>既有决策</h3><pre>{{ pretty(detail.decisions) }}</pre>
      <form v-if="detail.status === 'open'" class="stack" @submit.prevent="submitDecision">
        <label>处理方式<select v-model="decision.action" aria-label="处理方式"><option value="confirm">确认原评分</option><option value="adjust_score">改分</option><option value="request_regrade">重新批改</option><option value="report_rule_problem">报告规则问题</option></select></label>
        <label v-if="decision.action === 'adjust_score'">最终分数<input v-model.number="decision.score" aria-label="最终分数" required type="number" min="0" :max="detail.grading.max_score" step="any"></label>
        <label v-if="requiresReason">处理理由<textarea v-model.trim="decision.reason" aria-label="处理理由" required rows="3" /></label>
        <button class="button primary" :disabled="saving" type="submit">保存复核决策</button>
      </form>
      <button v-if="detail.status === 'resolved'" class="button primary" :disabled="saving" type="button" @click="publishResult">发布此学生成绩</button>
    </section>
  </main>
</template>

<script setup lang="ts">
import { fetchCurrentPrincipal } from '../../lib/student-api'
import { batchConfirmReviewTasks, decideReviewTask, fetchTeacherReviewTask, fetchTeacherReviewTasks, fetchTeacherWorkspace, publishAttemptResults, type TeacherReviewTask, type TeacherReviewTaskDetail } from '../../lib/teacher-api'

const workspace = ref<{ classes: Array<{ id: string; code: string; name: string }>; assignments: Array<{ id: string; title: string }> }>({ classes: [], assignments: [] })
const tasks = ref<TeacherReviewTask[]>([])
const activeTask = ref<TeacherReviewTask | null>(null)
const detail = ref<TeacherReviewTaskDetail | null>(null)
const message = ref('')
const loading = ref(false)
const saving = ref(false)
const batchTaskIds = ref<string[]>([])
const questionTypes = ['M1', 'M2', 'E1', 'E2', 'E3', 'E4']
const filters = reactive({ class_id: '', assignment_id: '', subject: '', question_type: '', reason: '' })
const decision = reactive({ action: 'confirm', score: 0, reason: '' })
const requiresReason = computed(() => ['adjust_score', 'request_regrade', 'report_rule_problem'].includes(decision.action))
const pretty = (value: unknown) => JSON.stringify(value, null, 2)

async function csrfToken(): Promise<string> {
  const principal = await fetchCurrentPrincipal($fetch)
  if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。')
  return principal.csrf_token
}

async function loadTasks() {
  loading.value = true
  message.value = ''
  try {
    const result = await fetchTeacherReviewTasks($fetch, filters)
    tasks.value = result.review_tasks
    batchTaskIds.value = []
  } catch { message.value = '暂时无法读取复核队列，请检查网络或权限。' }
  finally { loading.value = false }
}

async function selectTask(task: TeacherReviewTask) {
  activeTask.value = task
  detail.value = null
  message.value = ''
  try { detail.value = await fetchTeacherReviewTask($fetch, task.id) }
  catch { message.value = '暂时无法读取复核证据，任务可能已被其他教师处理。' }
}

async function submitDecision() {
  if (!activeTask.value || !detail.value) return
  if (requiresReason.value && !decision.reason) { message.value = '改分、重批和报告规则问题必须填写处理理由。'; return }
  saving.value = true
  try {
    await decideReviewTask($fetch, await csrfToken(), activeTask.value.id, {
      action: decision.action, version: detail.value.version,
      ...(decision.action === 'adjust_score' ? { score: Number(decision.score) } : {}),
      ...(requiresReason.value ? { reason: decision.reason } : {}),
    })
    detail.value = await fetchTeacherReviewTask($fetch, activeTask.value.id)
    await loadTasks()
    message.value = decision.action === 'request_regrade' ? '已提交重批，新的复核任务已进入队列。' : '复核决策已保存。'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '保存失败，任务可能已变更。' }
  finally { saving.value = false }
}

async function confirmBatch() {
  const selected = tasks.value.filter((task) => batchTaskIds.value.includes(task.id))
  const assignmentId = selected[0]?.assignment_id
  if (!assignmentId || selected.some((task) => task.assignment_id !== assignmentId)) { message.value = '批量确认只能选择同一作业的确定性答案。'; return }
  saving.value = true
  try {
    await batchConfirmReviewTasks($fetch, await csrfToken(), assignmentId, batchTaskIds.value)
    await loadTasks()
    message.value = '确定性答案已批量确认。'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '批量确认失败，部分任务可能已变更。' }
  finally { saving.value = false }
}

async function publishResult() {
  if (!activeTask.value) return
  saving.value = true
  try {
    await publishAttemptResults($fetch, await csrfToken(), activeTask.value.assignment_id, activeTask.value.attempt_id)
    message.value = '学生成绩已发布。'
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '无法发布：该尝试可能还有未解决的复核任务。' }
  finally { saving.value = false }
}

onMounted(async () => {
  try { workspace.value = await fetchTeacherWorkspace($fetch) }
  catch { message.value = '暂时无法读取教师工作台。' }
  await loadTasks()
})
</script>
