<template>
  <section class="stack" aria-labelledby="curriculum-import-heading">
    <div>
      <p class="eyebrow">受控导入</p>
      <h1 id="curriculum-import-heading">导入课程目录</h1>
      <p class="notice">先执行 dry-run 查看规范化结果和变更，再创建待审核草稿。</p>
    </div>

    <p v-if="message" class="notice" role="status">{{ message }}</p>

    <p v-if="!schema" data-testid="curriculum-import-loading">正在加载导入格式说明…</p>

    <div v-else data-testid="curriculum-import-ready">
    <label>
      导入格式
      <select v-model="format" aria-label="导入格式">
        <option value="json">JSON</option>
        <option value="csv">CSV</option>
      </select>
    </label>

    <template v-if="format === 'json'">
      <label>
        JSON 课程目录
        <textarea v-model="documentText" aria-label="JSON 课程目录" rows="16" />
      </label>
    </template>
    <template v-else>
      <label>
        CSV 课程目标
        <textarea v-model="documentText" aria-label="CSV 课程目标" rows="16" />
      </label>
      <label>
        课程方案 JSON
        <textarea v-model="profileText" aria-label="课程方案 JSON" rows="5" />
      </label>
      <label>
        来源 JSON
        <textarea v-model="sourceText" aria-label="来源 JSON" rows="5" />
      </label>
      <label>
        年级映射 JSON
        <textarea v-model="gradeMappingsText" aria-label="年级映射 JSON" rows="5" />
      </label>
    </template>

    <div class="actions">
      <button
        class="button primary"
        data-testid="run-curriculum-dry-run"
        type="button"
        :disabled="loading"
        @click="runDryRun"
      >
        {{ loading ? '分析中…' : '执行 dry-run' }}
      </button>
      <button
        class="button secondary"
        data-testid="create-curriculum-draft"
        type="button"
        :disabled="creating || !analysis?.can_apply"
        @click="createDraft"
      >
        {{ creating ? '创建中…' : '创建待审核草稿' }}
      </button>
    </div>

    <section v-if="analysis" class="stack" aria-labelledby="curriculum-analysis-heading">
      <h2 id="curriculum-analysis-heading">dry-run 结果</h2>
      <p>目录指纹：<code>{{ analysis.catalogue_fingerprint }}</code></p>
      <p>新增 {{ analysis.additions.length }} 项，更新 {{ analysis.updates.length }} 项，未变化 {{ analysis.unchanged.length }} 项。</p>

      <div v-if="analysis.problems.length || analysis.conflicts.length" class="notice" role="alert">
        <h3>需要处理的问题</h3>
        <ul>
          <li v-for="problem in [...analysis.problems, ...analysis.conflicts]" :key="`${problem.code}-${problem.source_path ?? ''}-${problem.source_row ?? ''}`">
            {{ problem.message }}
          </li>
        </ul>
      </div>
      <p v-else class="notice" role="status">校验通过，可以创建待审核草稿。</p>
    </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchCurrentPrincipal } from '../../lib/student-api'
import {
  createCurriculumImport,
  dryRunCurriculumImport,
  fetchCurriculumImportSchema,
  type CurriculumImportAnalysis,
  type CurriculumImportSchema,
} from '../../lib/admin-curriculum'

const format = ref<'json' | 'csv'>('json')
const documentText = ref('')
const profileText = ref('{}')
const sourceText = ref('{}')
const gradeMappingsText = ref('{}')
const schema = ref<CurriculumImportSchema | null>(null)
const analysis = ref<CurriculumImportAnalysis | null>(null)
const loading = ref(false)
const creating = ref(false)
const message = ref('')

onMounted(async () => {
  try {
    schema.value = await fetchCurriculumImportSchema($fetch)
  } catch {
    message.value = '无法加载导入格式说明，请稍后重试。'
  }
})

function parseJson(value: string, label: string): unknown {
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`${label} 不是有效 JSON`)
  }
}

function buildBody(): Record<string, unknown> | null {
  try {
    if (format.value === 'json') {
      return { format: 'json', document: parseJson(documentText.value, '课程目录') }
    }
    return {
      format: 'csv',
      document: documentText.value,
      profile: parseJson(profileText.value, '课程方案'),
      source: parseJson(sourceText.value, '来源'),
      grade_mappings: parseJson(gradeMappingsText.value, '年级映射'),
    }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '导入内容格式不正确'
    return null
  }
}

async function csrfToken(): Promise<string> {
  const principal = await fetchCurrentPrincipal($fetch)
  if (!principal.csrf_token) throw new Error('当前会话缺少 CSRF token')
  return principal.csrf_token
}

async function runDryRun(): Promise<void> {
  const body = buildBody()
  if (!body) return
  loading.value = true
  message.value = ''
  try {
    analysis.value = await dryRunCurriculumImport($fetch, await csrfToken(), crypto.randomUUID(), body)
  } catch {
    message.value = 'dry-run 执行失败，请检查导入内容后重试。'
  } finally {
    loading.value = false
  }
}

async function createDraft(): Promise<void> {
  if (!analysis.value?.can_apply) return
  const body = buildBody()
  if (!body) return
  creating.value = true
  message.value = ''
  try {
    const created = await createCurriculumImport($fetch, await csrfToken(), crypto.randomUUID(), {
      ...body,
      catalogue_fingerprint: analysis.value.catalogue_fingerprint,
    })
    await navigateTo(`/platform/curriculum/imports/${encodeURIComponent(created.id)}`)
  } catch (error) {
    if (typeof error === 'object' && error !== null && (error as { statusCode?: unknown }).statusCode === 409) {
      message.value = '目录已变化，请重新执行 dry-run'
    } else {
      message.value = '创建待审核草稿失败，请稍后重试。'
    }
  } finally {
    creating.value = false
  }
}
</script>
