<script setup lang="ts">
import LogoutButton from '../../components/LogoutButton.vue'
import TeacherAiReviewWorkspace from '../../components/teacher/TeacherAiReviewWorkspace.vue'
import TeacherWorkbenchNav from '../../components/teacher/TeacherWorkbenchNav.vue'

useHead({ title: 'AI 出题审核' })
</script>

<template>
  <main class="teacher-workbench">
    <aside class="teacher-workbench__sidebar">
      <NuxtLink class="teacher-brand" to="/teacher">作业批改</NuxtLink>
      <p class="teacher-brand__role">教师工作区</p>
      <TeacherWorkbenchNav active-module="ai_questions" />
    </aside>

    <section class="teacher-workbench__content">
      <div class="shell teacher-page">
        <header class="teacher-topbar">
          <NuxtLink class="teacher-topbar__back" to="/teacher">← 返回教师工作台</NuxtLink>
          <LogoutButton />
        </header>
        <TeacherAiReviewWorkspace />
      </div>
    </section>
  </main>
</template>
