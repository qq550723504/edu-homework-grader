<template>
  <section class="teacher-module-page" aria-labelledby="assignment-workspace-title">
    <header class="teacher-page-heading"><div><p class="eyebrow">作业</p><h1 id="assignment-workspace-title">创建作业</h1><p class="teacher-page-heading__copy">班级、题目版本与截止时间被组织为一条清晰的发布路径。</p></div></header>
    <div class="teacher-workspace">
      <aside class="teacher-workspace__aside"><span class="tag">作业</span><h2>还没有作业草稿</h2><p>先填写基本信息。题目版本将在题库发布后出现在这里，避免把未发布题目带入课堂。</p></aside>
      <form class="teacher-form" @submit.prevent="submit">
        <div class="teacher-form__heading"><h2>作业草稿</h2><p>带 <span aria-hidden="true">*</span> 的字段为必填项</p></div>
        <div class="teacher-field"><label for="assignment-title">作业标题 <span aria-hidden="true">*</span></label><input id="assignment-title" v-model="draft.title" required placeholder="例如：第 3 周数学练习" /></div>
        <div class="teacher-field"><label for="assignment-class">班级 <span aria-hidden="true">*</span></label><select id="assignment-class" v-model="draft.className" required><option disabled value="">选择班级</option><option value="三年级 2 班">三年级 2 班</option><option value="三年级 3 班">三年级 3 班</option></select></div>
        <div class="teacher-field"><label for="assignment-items">题目版本</label><select id="assignment-items" disabled><option>暂无已发布题目</option></select></div>
        <div class="teacher-field"><label for="assignment-due">截止时间 <span aria-hidden="true">*</span></label><input id="assignment-due" v-model="draft.dueAt" required type="datetime-local" /></div>
        <label class="teacher-checkbox"><input v-model="draft.allowLate" type="checkbox" /> 允许迟交</label>
        <p v-if="submitted" class="teacher-form__message" role="status">作业信息已通过本页校验，可在题目版本就绪后继续发布。</p>
        <button class="button primary teacher-form__submit" type="submit" :disabled="!ready">创建作业草稿</button>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { isAssignmentDraftReady, type AssignmentDraft } from '../../lib/teacher-workbench'

const draft = reactive<AssignmentDraft>({ title: '', className: '', dueAt: '', allowLate: false })
const submitted = ref(false)
const ready = computed(() => isAssignmentDraftReady(draft))

function submit() { submitted.value = true }
</script>
