// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AdminPage from '../app/pages/admin/index.vue'

vi.mock('../app/lib/admin-generation-defaults', () => ({
  fetchGenerationDefaults: vi.fn().mockRejectedValue(Object.assign(new Error('not authorized'), { statusCode: 404 })),
  submitGenerationDefaultChange: vi.fn(),
  decideGenerationDefaultChange: vi.fn(),
  rollbackGenerationDefaultChange: vi.fn(),
}))

vi.mock('../app/lib/student-api', () => ({ fetchCurrentPrincipal: vi.fn() }))

describe('admin governance rendering', () => {
  beforeEach(() => {
    vi.stubGlobal('$fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hides platform-only governance controls when the summary cannot be authorized', async () => {
    const wrapper = mount(
      {
        components: { AdminPage },
        template: '<Suspense><AdminPage /></Suspense>',
      },
      {
        global: {
          stubs: {
            LogoutButton: true,
            NuxtLink: { template: '<a><slot /></a>' },
          },
        },
      },
    )
    await flushPromises()

    expect(wrapper.text()).toContain('当前账号无平台治理权限。')
    expect(wrapper.text()).not.toContain('AI 默认配置治理')

    wrapper.unmount()
  })
})
