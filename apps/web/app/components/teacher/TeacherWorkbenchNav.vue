<template>
  <nav class="teacher-nav" aria-label="教师工作区">
    <button
      v-for="module in teacherModules"
      :key="module.id"
      class="teacher-nav__item"
      :class="{ 'teacher-nav__item--active': activeModule === module.id }"
      type="button"
      :aria-current="activeModule === module.id ? 'page' : undefined"
      @click="emit('select', module.id)"
    >
      <span>{{ module.label }}</span>
      <span v-if="module.badge" class="teacher-nav__badge">{{ module.badge }}</span>
    </button>
  </nav>
</template>

<script setup lang="ts">
import { teacherModules, type TeacherModule } from '../../lib/teacher-workbench'

defineProps<{ activeModule: TeacherModule }>()

const emit = defineEmits<{ select: [module: TeacherModule] }>()
</script>
