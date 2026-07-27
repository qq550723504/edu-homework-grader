<script setup lang="ts">
import type { TeacherAiGenerationJob } from '../../lib/teacher-ai-review'

const failureSummaryLabels: Record<string, string> = {
  objective_revision_mismatch: '课程目标与生成计划不一致',
  question_type_mismatch: '题型与生成计划不一致',
  difficulty_out_of_tolerance: '难度偏离目标范围',
  policy_rule_invalid: '评分规则不符合平台要求',
  unexpected_candidate_ordinal: '返回了计划外的候选题',
}

defineProps<{
  jobs: TeacherAiGenerationJob[]
  selectedJobId?: string | null
}>()

const emit = defineEmits<{
  'select-job': [jobId: string]
}>()
</script>

<template>
  <section aria-label="AI 出题批次">
    <ul>
      <li v-for="job in jobs" :key="job.id">
        <button
          :aria-current="selectedJobId === job.id ? 'true' : undefined"
          :data-testid="`generation-job-${job.id}`"
          type="button"
          @click="emit('select-job', job.id)"
        >
          <span>批次 {{ job.subject || job.id }}</span>
          <span>状态：{{ job.status }}</span>
          <span>成功 {{ job.succeeded_count ?? 0 }}</span>
          <span>失败 {{ job.failed_count ?? 0 }}</span>
          <span v-for="code in job.failure_summary ?? []" :key="code">
            原因：{{ failureSummaryLabels[code] }}
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>
