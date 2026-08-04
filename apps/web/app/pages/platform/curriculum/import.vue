<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/platform/curriculum">← 返回课程目录管理</NuxtLink>
    <LogoutButton />
    <CurriculumImportWorkspace />
  </main>
</template>

<script setup lang="ts">
import CurriculumImportWorkspace from '../../../components/admin/CurriculumImportWorkspace.vue'

useHead({ title: '导入课程目录' })
</script>
