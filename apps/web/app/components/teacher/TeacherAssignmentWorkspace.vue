<template>
  <section class="teacher-module-page" aria-labelledby="assignment-workspace-title">
    <header class="teacher-page-heading"><div><p class="eyebrow">作业</p><h1 id="assignment-workspace-title">创建作业</h1><p class="teacher-page-heading__copy">班级、题目版本与截止时间被组织为一条清晰的发布路径。</p></div></header>
    <div class="teacher-workspace">
      <aside class="teacher-workspace__aside"><span class="tag">作业</span><h2>还没有作业草稿</h2><p>先填写基本信息。题目版本将在题库发布后出现在这里，避免把未发布题目带入课堂。</p></aside>
      <div class="teacher-workspace__content"><slot /></div>
    </div>
  </section>
</template>
