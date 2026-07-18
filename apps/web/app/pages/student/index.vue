<template>
  <main class="shell narrow">
    <NuxtLink class="back" to="/">← 返回</NuxtLink>
    <p class="eyebrow">学生端</p>
    <h1>今天的作业</h1>
    <section class="stack">
      <article class="assignment">
        <div>
          <span class="subject math">数学</span>
          <h2>整式化简</h2>
          <p>10 题 · 截止今天 20:00</p>
        </div>
        <button class="button primary" type="button">开始作答</button>
      </article>
      <article class="assignment">
        <div>
          <span class="subject english">英语</span>
          <h2>Unit 4 复习</h2>
          <p>12 题 · 截止明天 18:00</p>
        </div>
        <button class="button primary" type="button">继续作答</button>
      </article>
    </section>
    <p class="notice">当前页面为启动骨架，下一步接入登录、作业 API、离线保存和 MathLive。</p>
  </main>
</template>
