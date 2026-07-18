<script setup lang="ts">
const config = useRuntimeConfig()
</script>

<template>
  <main class="shell">
    <section class="hero">
      <p class="eyebrow">MVP · 第一阶段</p>
      <h1>英语与数学作业批改平台</h1>
      <p class="lede">
        围绕做作业、自动批改、教师复核与学生订正构建最小可用闭环。
      </p>
      <div class="actions">
        <NuxtLink class="button primary" to="/student">进入学生端</NuxtLink>
        <NuxtLink class="button secondary" to="/teacher">进入教师端</NuxtLink>
      </div>
    </section>

    <section class="grid" aria-label="平台能力">
      <article class="card">
        <span class="tag">英语</span>
        <h2>规则优先，语义辅助</h2>
        <p>先覆盖客观题、填空与限定句子；阅读简答进入教师复核。</p>
      </article>
      <article class="card">
        <span class="tag">数学</span>
        <h2>安全 AST 与符号等价</h2>
        <p>不执行学生字符串，使用白名单结构判断数值和表达式。</p>
      </article>
      <article class="card">
        <span class="tag">教师</span>
        <h2>证据、复核与追溯</h2>
        <p>评分结果保留规则、版本和证据，支持改分理由与申诉。</p>
      </article>
    </section>

    <footer class="footer">Core API: {{ config.public.apiBase }}</footer>
  </main>
</template>
