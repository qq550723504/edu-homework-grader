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

      <div class="teacher-workspace__content"><slot /></div>
    </div>
  </section>
</template>
