<template>
  <main class="homepage">
    <header class="homepage__header">
      <NuxtLink class="homepage__brand" to="/">Edu Homework Grader</NuxtLink>
      <nav class="homepage__nav" aria-label="官网导航">
        <a href="#platform-capabilities">平台能力</a><a href="#trust-principles">为什么可信</a>
        <NuxtLink class="button secondary" to="/student">进入学生工作台</NuxtLink>
        <NuxtLink class="button primary" to="/teacher">进入教师工作台</NuxtLink>
      </nav>
    </header>
    <section class="homepage__hero" aria-labelledby="homepage-title">
      <p class="eyebrow">英语与数学作业协作平台</p>
      <h1 id="homepage-title">让作业、反馈与教学协作更清楚</h1>
      <p class="lede">学生安心完成与订正，教师从容创建、跟进和复核，让每一步学习都有清晰的依据。</p>
      <div class="homepage__role-grid" aria-label="选择工作台">
        <article class="homepage__role-card homepage__student-entry"><p class="tag">学生</p><h2>完成作业，也读懂下一步</h2><p>查看学习任务、提交答案、获得反馈，并据此完成订正或申请复核。</p><NuxtLink class="button primary" to="/student">进入学生工作台</NuxtLink></article>
        <article class="homepage__role-card homepage__teacher-entry"><p class="tag">教师</p><h2>安排学习，也看见学习过程</h2><p>创建和布置任务、查看进展，及时处理需要专业判断的复核。</p><NuxtLink class="button secondary" to="/teacher">进入教师工作台</NuxtLink></article>
      </div>
    </section>
    <section class="homepage__section" aria-labelledby="audiences-title">
      <p class="eyebrow">为学习共同体而设计</p><h2 id="audiences-title">每个人都能看清学习正在发生什么</h2>
      <div class="homepage__audience-grid"><article><h3>学生</h3><p>把注意力放在作答、理解反馈和持续改进上。</p></article><article><h3>教师与学校</h3><p>用统一工作流连接出题、作业、学习进展与必要复核。</p></article><article><h3>家长</h3><p>通过清晰反馈理解孩子的学习过程与需要支持的地方。</p></article></div>
    </section>
    <section id="platform-capabilities" class="homepage__section homepage__section--tinted" aria-labelledby="capabilities-title">
      <p class="eyebrow">平台能力</p><h2 id="capabilities-title">从作业到订正，学习过程有迹可循</h2>
      <ol class="homepage__journey"><li><strong>01</strong><div><h3>英语与数学作业</h3><p>围绕课程任务完成在线作答。</p></div></li><li><strong>02</strong><div><h3>规则化反馈</h3><p>让每次作答获得稳定、可理解的反馈。</p></div></li><li><strong>03</strong><div><h3>教师复核</h3><p>把需要理解语境与专业判断的结果交给教师。</p></div></li><li><strong>04</strong><div><h3>订正与申诉</h3><p>学生根据反馈订正，并在需要时提出复核申请。</p></div></li></ol>
    </section>
    <section id="trust-principles" class="homepage__section" aria-labelledby="trust-title">
      <p class="eyebrow">为什么可信</p><h2 id="trust-title">技术辅助教学，但不取代教育判断</h2>
      <div class="homepage__trust-grid"><article><h3>一致的评分规则</h3><p>基础题以明确规则提供稳定判断依据。</p></article><article><h3>AI 辅助，不替代教师判断</h3><p>需要理解语境的结果保留给教师复核。</p></article><article><h3>反馈可追溯</h3><p>学生、教师都能回看反馈与后续处理。</p></article></div>
    </section>
    <footer class="homepage__footer"><div><p class="eyebrow">现在开始</p><h2>进入适合你的工作台</h2></div><div class="homepage__footer-actions"><NuxtLink class="button secondary" to="/student">进入学生工作台</NuxtLink><NuxtLink class="button primary" to="/teacher">进入教师工作台</NuxtLink></div></footer>
  </main>
</template>
