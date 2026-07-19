import { defineConfig, devices } from '@playwright/test'

const apiBaseUrl = 'http://127.0.0.1:18000'
const webBaseUrl = 'http://127.0.0.1:13000'

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  globalTeardown: './e2e/stop-e2e-api.mjs',
  use: {
    baseURL: webBaseUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'node e2e/start-e2e-api.mjs',
      url: `${apiBaseUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --port 13000',
      url: webBaseUrl,
      env: {
        NUXT_HOST: '127.0.0.1',
        NUXT_DEVTOOLS_ENABLED: 'false',
        NUXT_PUBLIC_API_BASE: apiBaseUrl,
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
