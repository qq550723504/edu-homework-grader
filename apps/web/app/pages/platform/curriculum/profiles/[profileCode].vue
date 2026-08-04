<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/platform/curriculum">← 返回课程目录管理</NuxtLink>
    <LogoutButton />
    <CurriculumProfileDetail :profile-code="String(route.params.profileCode)" />
  </main>
</template>

<script setup lang="ts">
import CurriculumProfileDetail from '../../../../components/admin/CurriculumProfileDetail.vue'

const route = useRoute()
useHead({ title: '课程方案详情' })
</script>
