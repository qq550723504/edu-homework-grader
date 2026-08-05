<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/platform/curriculum">← 返回课程目录管理</NuxtLink>
    <LogoutButton />
    <CurriculumImportDetail :batch-id="String(route.params.batchId)" />
  </main>
</template>

<script setup lang="ts">
import CurriculumImportDetail from '../../../../components/admin/CurriculumImportDetail.vue'

const route = useRoute()
useHead({ title: '课程目录导入批次' })
</script>
