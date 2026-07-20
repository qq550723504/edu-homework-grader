<template>
  <section class="teacher-module-page" aria-labelledby="question-workspace-title">
    <header class="teacher-page-heading">
      <div>
        <p class="eyebrow">题库</p>
        <h1 id="question-workspace-title">创建题目</h1>
        <p class="teacher-page-heading__copy">题目内容与答案规则集中在一个工作区，填写后可继续进入题库流程。</p>
      </div>
    </header>

    <div class="teacher-workspace">
      <aside class="teacher-workspace__aside">
        <span class="tag">题库</span>
        <h2>从一题开始</h2>
        <p>当前题库暂无题目。创建后可为题目补充测试用例，并发布为作业题目版本。</p>
      </aside>

      <form class="teacher-form" @submit.prevent="submit">
        <div class="teacher-form__heading"><h2>题目草稿</h2><p>带 <span aria-hidden="true">*</span> 的字段为必填项</p></div>
        <div class="teacher-field"><label for="question-title">题目标题 <span aria-hidden="true">*</span></label><input id="question-title" v-model="draft.title" required placeholder="例如：两位数加法练习" /></div>
        <div class="teacher-field"><label for="question-prompt">题干 <span aria-hidden="true">*</span></label><textarea id="question-prompt" v-model="draft.prompt" required rows="5" placeholder="输入学生需要完成的题目内容"></textarea></div>
        <div class="teacher-field"><label for="question-type">题型 <span aria-hidden="true">*</span></label><select id="question-type" v-model="draft.questionType"><option value="math">数值题</option><option value="text">文本题</option></select></div>
        <div class="teacher-field"><label for="question-answer">正确答案 <span aria-hidden="true">*</span></label><input id="question-answer" v-model="draft.answer" required placeholder="输入正确答案" /></div>
        <p v-if="submitted" class="teacher-form__message" role="status">题目内容已通过本页校验，可继续进入题库流程。</p>
        <button class="button primary teacher-form__submit" type="submit" :disabled="!ready">创建题目草稿</button>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { isQuestionDraftReady, type QuestionDraft } from '../../lib/teacher-workbench'

const draft = reactive<QuestionDraft>({ title: '', prompt: '', questionType: 'math', answer: '' })
const submitted = ref(false)
const ready = computed(() => isQuestionDraftReady(draft))

function submit() {
  submitted.value = true
}
</script>
