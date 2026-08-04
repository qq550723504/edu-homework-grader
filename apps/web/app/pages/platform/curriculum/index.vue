<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/platform">← 返回平台管理</NuxtLink>
    <LogoutButton />
    <p class="eyebrow">课程目录</p>
    <h1>课程目录管理</h1>
    <p class="notice">通过受控导入、审核和激活维护课程目标。</p>

    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <p v-if="loading">正在加载课程目录…</p>
    <template v-else-if="accessDenied">
      <p role="status">当前账号没有课程目录管理权限。</p>
    </template>
    <template v-else>
      <div class="actions">
        <NuxtLink class="button primary" to="/platform/curriculum/import">导入课程目录</NuxtLink>
        <label>导入批次状态
          <select v-model="statusFilter" aria-label="批次状态">
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="in_review">审核中</option>
            <option value="active">已激活</option>
            <option value="retired">已退休</option>
          </select>
        </label>
      </div>

      <section class="stack" aria-labelledby="curriculum-profiles-heading">
        <h2 id="curriculum-profiles-heading">课程方案</h2>
        <p v-if="profiles.items.length === 0">暂无课程方案。</p>
        <ul v-else>
          <li v-for="profile in profiles.items" :key="profile.id">
            <NuxtLink :to="`/platform/curriculum/profiles/${encodeURIComponent(profile.code)}`">
              {{ profile.name }} / {{ profile.version_label }}
            </NuxtLink>
            <span> · {{ profile.status }} · {{ profile.objective_count ?? 0 }} 个课程目标</span>
          </li>
        </ul>
        <div class="actions" aria-label="课程方案分页">
          <button class="button secondary" data-testid="previous-curriculum-profile-page" type="button" :disabled="profileOffset === 0" @click="previousProfiles">上一页</button>
          <button class="button secondary" data-testid="next-curriculum-profile-page" type="button" :disabled="profileOffset + profiles.limit >= profiles.total" @click="nextProfiles">下一页</button>
        </div>
      </section>

      <section class="stack" aria-labelledby="curriculum-imports-heading">
        <h2 id="curriculum-imports-heading">导入批次</h2>
        <p v-if="imports.items.length === 0">暂无导入批次。</p>
        <ul v-else>
          <li v-for="batch in imports.items" :key="batch.id">
            <NuxtLink :to="`/platform/curriculum/imports/${batch.id}`">
              {{ batch.profile.name }} / {{ batch.input_format }} / {{ batch.status }}
            </NuxtLink>
            <span> · {{ batch.change_summary }}</span>
          </li>
        </ul>
        <div class="actions" aria-label="导入批次分页">
          <button class="button secondary" data-testid="previous-curriculum-import-page" type="button" :disabled="importOffset === 0" @click="previousImports">上一页</button>
          <button class="button secondary" data-testid="next-curriculum-import-page" type="button" :disabled="importOffset + imports.limit >= imports.total" @click="nextImports">下一页</button>
        </div>
      </section>
    </template>
  </main>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import {
  fetchAdminCurriculumProfiles,
  fetchCurriculumImports,
  type CurriculumPage,
  type CurriculumAdminProfile,
  type CurriculumImportSummary,
  type CurriculumStatus,
} from '../../../lib/admin-curriculum'

const loading = ref(true)
const accessDenied = ref(false)
const message = ref('')
const statusFilter = ref<CurriculumStatus | ''>('')
const profiles = ref<CurriculumPage<CurriculumAdminProfile>>({ items: [], total: 0, limit: 50, offset: 0 })
const imports = ref<CurriculumPage<CurriculumImportSummary>>({ items: [], total: 0, limit: 50, offset: 0 })
const profileOffset = ref(0)
const importOffset = ref(0)

function isAuthorizationFailure(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false
  const statusCode = (error as { statusCode?: unknown }).statusCode
  return statusCode === 403 || statusCode === 404
}

async function load(): Promise<void> {
  loading.value = true
  accessDenied.value = false
  message.value = ''
  const profileQuery = { limit: 50, offset: profileOffset.value }
  const importQuery = statusFilter.value
    ? { status: statusFilter.value, limit: 50, offset: importOffset.value }
    : { limit: 50, offset: importOffset.value }
  try {
    const [nextProfiles, nextImports] = await Promise.all([
      fetchAdminCurriculumProfiles($fetch, profileQuery),
      fetchCurriculumImports($fetch, importQuery),
    ])
    profiles.value = nextProfiles
    imports.value = nextImports
  } catch (error) {
    accessDenied.value = isAuthorizationFailure(error)
    if (!accessDenied.value) message.value = '暂时无法加载课程目录，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function previousProfiles(): void {
  profileOffset.value = Math.max(0, profileOffset.value - profiles.value.limit)
  void load()
}

function nextProfiles(): void {
  if (profileOffset.value + profiles.value.limit >= profiles.value.total) return
  profileOffset.value += profiles.value.limit
  void load()
}

function previousImports(): void {
  importOffset.value = Math.max(0, importOffset.value - imports.value.limit)
  void load()
}

function nextImports(): void {
  if (importOffset.value + imports.value.limit >= imports.value.total) return
  importOffset.value += imports.value.limit
  void load()
}

watch(statusFilter, () => {
  importOffset.value = 0
  void load()
})
await load()
</script>
