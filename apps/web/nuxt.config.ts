export default defineNuxtConfig({
  compatibilityDate: '2026-07-01',
  devtools: { enabled: process.env.NUXT_DEVTOOLS_ENABLED !== 'false' },
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: 'Edu Homework Grader｜作业、反馈与教学协作平台',
      meta: [
        {
          name: 'description',
          content: '面向学生、教师与学校的英语和数学作业协作平台，连接作业、反馈、教师复核与订正。'
        }
      ]
    }
  },
  runtimeConfig: {
    appEnv: process.env.NUXT_APP_ENV ?? process.env.APP_ENV ?? 'development',
    coreApiBase: process.env.NUXT_CORE_API_BASE ?? 'http://localhost:8000',
    oidcClientId: process.env.NUXT_OIDC_CLIENT_ID ?? 'edu-grader-web',
    oidcIssuer: process.env.NUXT_OIDC_ISSUER ?? 'http://localhost:8080/realms/edu-grader',
    sessionPassword: process.env.NUXT_SESSION_PASSWORD ?? 'development-only-session-password-change-me',
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? 'http://localhost:8000'
    }
  },
  vite: {
    optimizeDeps: {
      include: ['mathlive', '@cortex-js/compute-engine', 'dexie']
    }
  }
})
