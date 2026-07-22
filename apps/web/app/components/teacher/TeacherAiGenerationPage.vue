<script setup lang="ts">
import LogoutButton from '../LogoutButton.vue'
import TeacherWorkbenchNav from './TeacherWorkbenchNav.vue'
import TeacherAiGenerationForm from './TeacherAiGenerationForm.vue'
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
          <NuxtLink class="teacher-topbar__back" to="/teacher/ai-questions">← 返回 AI 出题审核</NuxtLink>
          <LogoutButton />
        </header>
        <TeacherAiGenerationForm />
      </div>
    </section>
  </main>
</template>
