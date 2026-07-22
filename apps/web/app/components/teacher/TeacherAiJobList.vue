<script setup lang="ts">
import type { TeacherAiGenerationJob } from '../../lib/teacher-ai-review'

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
          <span>批次 {{ job.id }}</span>
          <span>状态：{{ job.status }}</span>
          <span>成功 {{ job.succeeded_count ?? 0 }}</span>
          <span>失败 {{ job.failed_count ?? 0 }}</span>
        </button>
      </li>
    </ul>
  </section>
</template>
