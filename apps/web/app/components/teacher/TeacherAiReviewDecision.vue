<script setup lang="ts">
import { computed } from 'vue'

import type { TeacherAiDraft, TeacherAiValidationRun } from '../../lib/teacher-ai-review'

const props = defineProps<{
  draft: TeacherAiDraft
  validation: TeacherAiValidationRun | null
}>()

const state = computed(() => {
  if (props.draft.teacher_state === 'accepted') return {
    heading: '已创建题库草稿', nextStep: '请前往题库测试并发布；学生尚未看到这道题。',
  }
  if (props.draft.teacher_state === 'rejected') return {
    heading: '已拒绝', nextStep: '该候选保留审核记录，不能再修改或接受。',
  }
  if (!props.validation || props.validation.status === 'blocked') return {
    heading: '暂不能接受', nextStep: '请修改题目、重新生成或拒绝；阻断问题解决前不能创建草稿。',
  }
  if (props.validation.status === 'warning') return {
    heading: '可接受，但请先确认提醒', nextStep: '阅读每条提醒后，勾选“我已阅读提醒”才能接受。',
  }
  return { heading: '可以接受', nextStep: '接受后会创建题库草稿，仍需测试和发布。' }
})
</script>

<template>
  <section data-testid="ai-review-decision" class="ai-review-decision" aria-label="审核结论">
    <p class="eyebrow">审核结论</p>
    <h2 data-testid="review-decision-heading">{{ state.heading }}</h2>
    <p data-testid="review-decision-next-step">{{ state.nextStep }}</p>
    <ul v-if="validation?.findings.length">
      <li v-for="finding in validation.findings" :key="finding.code">
        <strong>{{ finding.code }}</strong>：{{ finding.remediation }}
      </li>
    </ul>
  </section>
</template>

<style scoped>
.ai-review-decision { display: grid; gap: 10px; padding: 20px; border: 1px solid #bfd2f9; border-radius: 16px; background: #f4f8ff; }
.ai-review-decision h2, .ai-review-decision p { margin: 0; }
.ai-review-decision h2 { font-size: 1.25rem; }
.ai-review-decision ul { display: grid; gap: 8px; margin: 0; padding-left: 20px; color: #53647e; }
</style>
