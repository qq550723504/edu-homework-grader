<template>
  <main class="shell homepage">
    <section class="hero">
      <p class="eyebrow">作业学习平台</p>
      <h1>开始你的作业与教学工作</h1>
      <p class="lede">
        学生专注完成作业与订正，教师专注创建任务、查看结果与及时复核。
      </p>
    </section>

    <section class="role-grid" aria-label="选择工作区">
      <article class="role-card">
        <span class="tag">学生</span>
        <h2>完成今天的学习任务</h2>
        <p>查看待完成作业，提交答案，并根据反馈完成订正。</p>
        <NuxtLink class="button primary" to="/student">查看我的作业</NuxtLink>
      </article>
      <article class="role-card">
        <span class="tag">教师</span>
        <h2>安排与跟进学习</h2>
        <p>创建作业，查看批改结果，并处理需要你复核的任务。</p>
        <NuxtLink class="button secondary" to="/teacher">进入教学工作台</NuxtLink>
      </article>
    </section>

    <section class="trust-section" aria-labelledby="trust-heading">
      <div>
        <p class="eyebrow">学习过程更清楚</p>
        <h2 id="trust-heading">为什么值得信赖</h2>
      </div>
      <div class="trust-grid">
        <article class="card">
          <h3>一致的批改规则</h3>
          <p>基础题按明确规则评分，让每次作答都有稳定的判断依据。</p>
        </article>
        <article class="card">
          <h3>教师及时复核</h3>
          <p>需要理解语境的答案会进入教师复核，保留专业判断的空间。</p>
        </article>
        <article class="card">
          <h3>反馈可追溯</h3>
          <p>学生能据反馈完成订正，教师也能回看评分依据与处理记录。</p>
        </article>
      </div>
    </section>

    <footer class="footer">面向英语与数学作业的学习与教学协作平台</footer>
  </main>
</template>
