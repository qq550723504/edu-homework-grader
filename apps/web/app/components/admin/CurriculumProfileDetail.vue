<template>
  <section class="stack" aria-labelledby="curriculum-profile-detail-heading">
    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <p v-if="loading">正在加载课程方案…</p>
    <template v-else-if="profile">
      <div>
        <p class="eyebrow">课程方案</p>
        <h1 id="curriculum-profile-detail-heading">{{ profile.name }}</h1>
        <p>{{ profile.code }} · {{ profile.version_label }} · {{ profile.status }}</p>
      </div>
      <p>课程目标：{{ profile.objective_count ?? profile.objectives.length }} 项；年级映射：{{ profile.grade_mappings.length }} 项</p>

      <div class="actions">
        <button class="button secondary" type="button" @click="exportProfile">导出当前目录</button>
        <button v-if="profile.status === 'active'" class="button secondary" data-testid="load-retirement-impact" type="button" @click="loadImpact">评估退休影响</button>
        <button v-if="profile.status === 'active'" class="button secondary" data-testid="retire-curriculum-profile" type="button" :disabled="retiring || !canRetire" @click="retire">退休此目录</button>
      </div>

      <pre v-if="exportedDocument" aria-label="导出目录">{{ JSON.stringify(exportedDocument, null, 2) }}</pre>
      <section v-if="retirement" class="notice" aria-labelledby="retirement-impact-heading">
        <h2 id="retirement-impact-heading">退休影响</h2>
        <pre>{{ JSON.stringify(retirement, null, 2) }}</pre>
      </section>

      <section aria-labelledby="curriculum-objectives-heading">
        <h2 id="curriculum-objectives-heading">课程目标</h2>
        <ul>
          <li v-for="objective in profile.objectives" :key="String(objective.id)">
            {{ objective.code }} · {{ objective.subject }} · {{ objective.domain }}
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchCurrentPrincipal } from '../../lib/student-api'
import {
  exportCurriculumProfile,
  fetchCurriculumProfile,
  fetchRetirementImpact,
  retireCurriculumProfile,
  type CurriculumProfileDetail,
} from '../../lib/admin-curriculum'

const props = defineProps<{ profileCode: string }>()
const profile = ref<CurriculumProfileDetail | null>(null)
const retirement = ref<Record<string, unknown> | null>(null)
const exportedDocument = ref<Record<string, unknown> | null>(null)
const loading = ref(true)
const retiring = ref(false)
const canRetire = ref(false)
const message = ref('')

onMounted(async () => {
  try {
    profile.value = await fetchCurriculumProfile($fetch, props.profileCode)
  } catch {
    message.value = '无法加载课程方案，请稍后重试。'
  } finally {
    loading.value = false
  }
})

async function exportProfile(): Promise<void> {
  try {
    exportedDocument.value = await exportCurriculumProfile($fetch, props.profileCode)
  } catch {
    message.value = '导出课程目录失败，请稍后重试。'
  }
}

async function loadImpact(): Promise<void> {
  if (!profile.value) return
  try {
    retirement.value = await fetchRetirementImpact($fetch, profile.value.id)
    canRetire.value = Array.isArray(retirement.value.references) && retirement.value.references.length === 0
  } catch {
    message.value = '无法评估退休影响，请稍后重试。'
  }
}

async function retire(): Promise<void> {
  if (!profile.value || !canRetire.value) return
  if (!globalThis.confirm('确认退休此课程目录？退休后不能继续用于新的出题任务。')) return
  retiring.value = true
  try {
    const principal = await fetchCurrentPrincipal($fetch)
    if (!principal.csrf_token) throw new Error('当前会话缺少 CSRF token')
    profile.value = { ...profile.value, ...await retireCurriculumProfile($fetch, principal.csrf_token, crypto.randomUUID(), profile.value.id) }
  } catch (error) {
    message.value = typeof error === 'object' && error !== null && (error as { statusCode?: unknown }).statusCode === 409
      ? '目录仍有引用，不能退休。'
      : '退休课程目录失败，请稍后重试。'
  } finally {
    retiring.value = false
  }
}
</script>
