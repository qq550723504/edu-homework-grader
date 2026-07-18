<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/">← 返回</NuxtLink>
    <p class="eyebrow">学生端</p>
    <h1>我的作业</h1>
    <p v-if="message" class="notice">{{ message }}</p>
    <section v-for="section in sections" :key="section.key" class="stack">
      <h2>{{ section.title }}</h2>
      <article v-for="assignment in assignments[section.key]" :key="assignment.id" class="assignment">
        <div><span class="subject">{{ assignment.subject }}</span><h3>{{ assignment.title }}</h3><p>截止 {{ formatTime(assignment.due_at) }}</p></div>
        <NuxtLink class="button primary" :to="'/student/assignments/' + assignment.id">进入作答</NuxtLink>
      </article>
      <p v-if="assignments[section.key].length === 0" class="notice">暂无作业</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { fetchStudentAssignments, type StudentAssignmentGroups } from '../../lib/student-api'
const config = useRuntimeConfig()
const token = useCookie<string | null>('edu_access_token')
const assignments = ref<StudentAssignmentGroups>({ pending: [], correction_required: [], completed: [] })
const message = ref('')
const sections: { key: keyof StudentAssignmentGroups; title: string }[] = [{ key: 'pending', title: '待完成' }, { key: 'correction_required', title: '待订正' }, { key: 'completed', title: '已完成' }]
const formatTime = (value: string) => new Date(value).toLocaleString()
onMounted(async () => {
  if (!token.value) { message.value = '正在等待登录状态…'; return }
  try { assignments.value = await fetchStudentAssignments(config.public.apiBase, token.value, $fetch) }
  catch { message.value = '暂时无法读取作业，请检查网络后重试。' }
})
</script>
