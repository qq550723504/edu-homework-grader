<template>
  <section class="teacher-overview" aria-labelledby="teacher-workbench-title">
    <header class="teacher-page-heading">
      <div>
        <p class="eyebrow">今日概览</p>
        <h1 id="teacher-workbench-title">教学工作台</h1>
        <p class="teacher-page-heading__copy">优先处理需要你决定的事项，再开始准备下一份作业。</p>
      </div>
      <button class="button primary" type="button" @click="emit('open-module', 'assignments')">创建作业</button>
    </header>

    <section class="teacher-metrics" aria-label="教学数据概览">
      <article v-for="metric in metrics" :key="metric.label" class="teacher-metric">
        <strong>{{ metric.value }}</strong>
        <span>{{ metric.label }}</span>
      </article>
    </section>

    <section class="teacher-overview-grid" aria-label="教师待办与快捷操作">
      <article class="teacher-panel teacher-panel--priority">
        <div class="teacher-panel__heading">
          <div><p class="teacher-panel__eyebrow">优先处理</p><h2>今日待办</h2></div>
          <span class="teacher-panel__hint">共 38 项</span>
        </div>
        <div class="teacher-task-list">
          <div class="teacher-task">
            <div><h3>复核待评分答案</h3><p>数学 · 三年级 2 班</p></div>
            <button class="button secondary" type="button" @click="emit('open-module', 'reviews')">开始复核</button>
          </div>
          <div class="teacher-task">
            <div><h3>处理学生申请</h3><p>延期提交 · 2 个新申请</p></div>
            <button class="button secondary" type="button" @click="emit('open-module', 'requests')">去处理</button>
          </div>
        </div>
      </article>

      <article class="teacher-panel teacher-panel--assignments">
        <div class="teacher-panel__heading">
          <div><p class="teacher-panel__eyebrow">作业进度</p><h2>进行中的作业</h2></div>
          <button class="teacher-text-button" type="button" @click="emit('open-module', 'assignments')">查看全部</button>
        </div>
        <div class="teacher-assignment-summary">
          <div><strong>分数的初步认识</strong><span>18 / 25 已提交</span></div>
          <div><strong>英语单词拼写</strong><span>截止明天 18:00</span></div>
        </div>
      </article>
    </section>

    <section class="teacher-quick-start" aria-label="快速创建">
      <article class="teacher-quick-start__card">
        <span class="tag">题库</span>
        <h2>准备一道新题</h2>
        <p>先建立题干与答案规则，再用于后续作业。</p>
        <button class="button secondary" type="button" @click="emit('open-module', 'questions')">创建题目</button>
      </article>
      <article class="teacher-quick-start__card">
        <span class="tag">作业</span>
        <h2>发布下一份作业</h2>
        <p>选择班级、题目版本与截止时间，完成课堂安排。</p>
        <button class="button secondary" type="button" @click="emit('open-module', 'assignments')">创建作业</button>
      </article>
    </section>
  </section>
</template>

<script setup lang="ts">
import type { TeacherModule } from '../../lib/teacher-workbench'

const props = defineProps<{
  reviewCount: number
  completionRate: number
  publishedAssignments: number
}>()

const emit = defineEmits<{ 'open-module': [module: TeacherModule] }>()

const metrics = computed(() => [
  { value: props.reviewCount, label: '待复核答案' },
  { value: `${props.completionRate}%`, label: '作业完成率' },
  { value: props.publishedAssignments, label: '已发布作业' }
])
</script>
