<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/">← 返回</NuxtLink><LogoutButton />
    <p class="eyebrow">管理员端</p>
    <h1>平台管理</h1>
    <p class="notice">管理员功能仅向平台管理员开放。</p>
    <section aria-label="AI 默认配置治理">
      <h2>AI 默认配置治理</h2>
      <p v-if="loading">正在加载…</p>
      <template v-else>
        <p v-if="summary?.current" data-testid="current-default-model">当前默认：{{ summary.current.provider_name }} / {{ summary.current.model_version }} / {{ summary.current.prompt_version }}</p>
        <p v-else>尚未配置默认生成模型和 Prompt。</p>
        <p v-if="message" role="status">{{ message }}</p>
        <form @submit.prevent="submit">
          <h3>提交晋级申请</h3>
          <label>Provider <input v-model.trim="providerName" required></label>
          <label>模型固定版本 <input v-model.trim="modelVersion" required></label>
          <label>Prompt 版本 <input v-model.trim="promptVersion" required></label>
          <label>申请说明 <input v-model.trim="requestReason" required></label>
          <label>运营评估报告 JSON <textarea v-model="evaluationReport" required></textarea></label>
          <button :disabled="saving" type="submit">提交晋级申请</button>
        </form>
        <h3>待审批</h3>
        <ul><li v-for="item in summary?.pending" :key="item.id">{{ item.model_version }} / {{ item.prompt_version }}：{{ item.request_reason }} <button :disabled="saving" type="button" @click="decide(item.id, 'approve')">批准</button><button :disabled="saving" type="button" @click="decide(item.id, 'reject')">拒绝</button></li></ul>
        <h3>历史</h3>
        <ul><li v-for="item in summary?.history" :key="item.id">{{ item.status }}：{{ item.model_version }} / {{ item.prompt_version }} <button v-if="item.status === 'approved'" :disabled="saving" type="button" @click="apply(item.id)">应用</button><button v-if="item.status === 'applied' || item.status === 'superseded'" :disabled="saving" type="button" @click="rollback(item.id)">申请回滚</button></li></ul>
      </template>
    </section>
  </main>
</template>

<script setup lang="ts">
import { fetchCurrentPrincipal } from '../../lib/student-api'
import { decideGenerationDefaultChange, fetchGenerationDefaults, rollbackGenerationDefaultChange, submitGenerationDefaultChange, type GenerationDefaultSummary } from '../../lib/admin-generation-defaults'
const summary = ref<GenerationDefaultSummary | null>(null)
const loading = ref(true)
const message = ref('')
const saving = ref(false)
const providerName = ref('openai')
const modelVersion = ref('')
const promptVersion = ref('generator-v1')
const requestReason = ref('')
const evaluationReport = ref('')
async function load() { loading.value = true; try { summary.value = await fetchGenerationDefaults($fetch) } catch { message.value = '无法加载治理配置。' } finally { loading.value = false } }
async function csrfToken(): Promise<string> { const principal = await fetchCurrentPrincipal($fetch); if (!principal.csrf_token) throw new Error('登录会话已过期，请重新登录。'); return principal.csrf_token }
async function decide(id: string, action: 'approve' | 'reject') { const reason = window.prompt(action === 'approve' ? '审批说明' : '拒绝原因')?.trim(); if (!reason) return; saving.value = true; try { await decideGenerationDefaultChange($fetch, await csrfToken(), id, action, reason); message.value = '操作已保存。'; await load() } catch { message.value = '操作失败。' } finally { saving.value = false } }
async function apply(id: string) { const reason = window.prompt('应用说明')?.trim(); if (!reason) return; saving.value = true; try { await decideGenerationDefaultChange($fetch, await csrfToken(), id, 'apply', reason); message.value = '默认配置已应用。'; await load() } catch { message.value = '应用失败。' } finally { saving.value = false } }
async function rollback(id: string) { const reason = window.prompt('回滚原因')?.trim(); if (!reason) return; saving.value = true; try { await rollbackGenerationDefaultChange($fetch, await csrfToken(), crypto.randomUUID(), id, reason); message.value = '已提交回滚申请。'; await load() } catch { message.value = '回滚申请失败。' } finally { saving.value = false } }
async function submit() {
  let report: Record<string, unknown>
  try { report = JSON.parse(evaluationReport.value) as Record<string, unknown> } catch { message.value = '运营评估报告必须是有效 JSON。'; return }
  saving.value = true
  try {
    await submitGenerationDefaultChange($fetch, await csrfToken(), crypto.randomUUID(), {
      provider_name: providerName.value, model_version: modelVersion.value, prompt_version: promptVersion.value,
      request_reason: requestReason.value, evaluation_report: report,
    })
    message.value = '已提交晋级申请。'
    evaluationReport.value = ''
    requestReason.value = ''
    await load()
  } catch { message.value = '晋级申请失败。' } finally { saving.value = false }
}
await load()
</script>
