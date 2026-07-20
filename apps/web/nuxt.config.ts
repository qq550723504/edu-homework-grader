export default defineNuxtConfig({
  compatibilityDate: '2026-07-01',
  devtools: { enabled: process.env.NUXT_DEVTOOLS_ENABLED !== 'false' },
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: '英语与数学作业批改平台',
      meta: [
        {
          name: 'description',
          content: '面向学生作答、教师复核与错题订正的英语和数学作业平台'
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
