<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/teacher">← 返回教师工作台</NuxtLink><LogoutButton />
    <p class="eyebrow">教师端 · 申诉</p>
    <h1>学生申诉</h1>
    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <section class="stack">
      <article v-for="appeal in appeals" :key="appeal.id" class="assignment">
        <div><span class="subject">{{ appeal.status }}</span><h2>{{ appeal.assignment_title }}</h2><p>{{ appeal.student_name || appeal.student_id }}：{{ appeal.reason }}</p><p v-if="appeal.decision_reason">处理理由：{{ appeal.decision_reason }}</p></div>
        <button v-if="appeal.status === 'open'" class="button secondary" type="button" @click="selectedAppeal = appeal">处理申诉</button>
      </article>
      <p v-if="appeals.length === 0" class="notice">当前没有可查看的学生申诉。</p>
    </section>
    <section v-if="selectedAppeal" class="card wide" aria-labelledby="appeal-decision-heading">
      <h2 id="appeal-decision-heading">处理申诉：{{ selectedAppeal.assignment_title }}</h2>
      <p>{{ selectedAppeal.reason }}</p>
      <form class="stack" @submit.prevent="submitDecision">
        <label>决定<select v-model="decision.approve" aria-label="申诉决定"><option :value="true">批准并创建订正机会</option><option :value="false">拒绝申诉</option></select></label>
        <label v-if="!decision.approve">拒绝理由<textarea v-model.trim="decision.reason" aria-label="拒绝理由" required rows="3" /></label>
        <button class="button primary" :disabled="saving" type="submit">保存申诉决定</button>
      </form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { fetchCurrentPrincipal } from '../../lib/student-api'
import { decideTeacherAppeal, fetchTeacherAppeals, type TeacherAppeal } from '../../lib/teacher-api'

const appeals = ref<TeacherAppeal[]>([])
const selectedAppeal = ref<TeacherAppeal | null>(null)
const message = ref('')
const saving = ref(false)
const decision = reactive({ approve: true, reason: '' })

async function loadAppeals() {
  try { appeals.value = (await fetchTeacherAppeals($fetch)).appeals }
  catch { message.value = '暂时无法读取申诉队列，请检查网络或权限。' }
}

async function csrfToken(): Promise<string> {
  const principal = await fetchCurrentPrincipal($fetch)
  if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。')
  return principal.csrf_token
}

async function submitDecision() {
  if (!selectedAppeal.value) return
  if (!decision.approve && !decision.reason) { message.value = '拒绝申诉必须填写理由。'; return }
  saving.value = true
  try {
    const result = await decideTeacherAppeal($fetch, await csrfToken(), selectedAppeal.value.id, {
      approve: decision.approve, version: selectedAppeal.value.version,
      ...(!decision.approve ? { reason: decision.reason } : {}),
    })
    message.value = result.correction_attempt_id ? '申诉已批准，已为学生创建订正机会。' : '申诉已拒绝。'
    selectedAppeal.value = null
    decision.reason = ''
    await loadAppeals()
  } catch (error: unknown) { message.value = error instanceof Error ? error.message : '保存失败，申诉可能已变更。' }
  finally { saving.value = false }
}

onMounted(loadAppeals)
</script>
