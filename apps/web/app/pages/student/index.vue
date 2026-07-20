<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/">← 返回</NuxtLink><button class="button secondary" type="button" @click="signOut">退出登录</button>
    <p class="eyebrow">学生端</p>
    <h1>我的作业</h1>
    <p v-if="message" class="notice">{{ message }}</p>
    <section v-for="section in sections" :key="section.key" class="stack">
      <h2>{{ section.title }}</h2>
      <article v-for="assignment in assignments[section.key]" :key="assignment.id" class="assignment">
        <div><span class="subject">{{ assignment.subject }}</span><h3>{{ assignment.title }}</h3><p>{{ studentAssignmentStatusLabel(assignment.status) }} · 截止 {{ formatTime(assignment.due_at) }}</p></div>
        <NuxtLink class="button primary" :to="'/student/assignments/' + assignment.id">进入作答</NuxtLink>
      </article>
      <p v-if="assignments[section.key].length === 0" class="notice">暂无作业</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { fetchStudentAssignments, studentAssignmentStatusLabel, type StudentAssignmentGroups } from '../../lib/student-api'
import { logout } from '../../lib/auth-client'
const assignments = ref<StudentAssignmentGroups>({ pending: [], correction_required: [], completed: [] })
const message = ref('')
const sections: { key: keyof StudentAssignmentGroups; title: string }[] = [{ key: 'pending', title: '待完成' }, { key: 'correction_required', title: '待订正' }, { key: 'completed', title: '已完成' }]
const formatTime = (value: string) => new Date(value).toLocaleString()
async function signOut() {
  await logout($fetch)
  return navigateTo('/')
}
onMounted(async () => {
  try { assignments.value = await fetchStudentAssignments($fetch) }
  catch { message.value = '暂时无法读取作业，请检查网络后重试。' }
})
</script>
