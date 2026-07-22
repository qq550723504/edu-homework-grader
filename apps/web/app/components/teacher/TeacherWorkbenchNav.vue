<template>
  <nav class="teacher-nav" aria-label="教师工作区">
    <NuxtLink
      v-for="module in teacherModules"
      :key="module.id"
      class="teacher-nav__item"
      :class="{ 'teacher-nav__item--active': activeModule === module.id }"
      :to="destination(module.id)"
      :aria-current="activeModule === module.id ? 'page' : undefined"
    >
      <span>{{ module.label }}</span>
      <span v-if="module.badge" class="teacher-nav__badge">{{ module.badge }}</span>
    </NuxtLink>
  </nav>
</template>

<script setup lang="ts">
import { teacherModules, type TeacherModule } from '../../lib/teacher-workbench'

defineProps<{ activeModule: TeacherModule }>()

function destination(module: TeacherModule) {
  if (module === 'reviews') return '/teacher/reviews'
  if (module === 'ai_questions') return '/teacher/ai-questions'
  if (module === 'requests') return '/teacher/appeals'
  return { hash: `#${module}` }
}
</script>
