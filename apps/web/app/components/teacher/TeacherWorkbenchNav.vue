<template>
  <nav class="teacher-nav" aria-label="教师工作区">
    <NuxtLink
      v-for="module in teacherModules"
      :key="module.id"
      class="teacher-nav__item"
      :class="{ 'teacher-nav__item--active': activeModule === module.id }"
      :to="{ hash: `#${module.id}` }"
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
</script>
