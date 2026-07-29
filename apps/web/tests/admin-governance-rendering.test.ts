// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AdminPage from '../app/pages/admin/index.vue'
import { decideGenerationDefaultChange, fetchGenerationDefaults } from '../app/lib/admin-generation-defaults'
import { fetchCurrentPrincipal } from '../app/lib/student-api'

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
    vi.stubGlobal('crypto', { randomUUID: vi.fn() })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
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

  it('reuses decision idempotency keys after ambiguous failures', async () => {
    vi.mocked(fetchGenerationDefaults).mockResolvedValue({
      current: null,
      pending: [{ id: 'pending-1', status: 'pending_approval', provider_name: 'fake', model_version: 'fake-v1', prompt_version: 'generator-v1', prompt_template_fingerprint: 'pending-fingerprint', request_reason: 'Review' }],
      history: [{ id: 'approved-1', status: 'approved', provider_name: 'fake', model_version: 'fake-v1', prompt_version: 'generator-v1', prompt_template_fingerprint: 'approved-fingerprint', request_reason: 'Apply' }],
    })
    vi.mocked(fetchCurrentPrincipal).mockResolvedValue({ csrf_token: 'csrf-token' } as never)
    vi.mocked(decideGenerationDefaultChange).mockRejectedValue(new Error('response lost'))
    vi.mocked(crypto.randomUUID).mockReturnValueOnce('approve-key').mockReturnValueOnce('reject-key').mockReturnValueOnce('apply-key')
    vi.stubGlobal('prompt', vi.fn().mockReturnValue('same reason'))
    const wrapper = mount({ components: { AdminPage }, template: '<Suspense><AdminPage /></Suspense>' }, {
      global: { stubs: { LogoutButton: true, NuxtLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    for (const [label, action, key] of [['批准', 'approve', 'approve-key'], ['拒绝', 'reject', 'reject-key'], ['应用', 'apply', 'apply-key']] as const) {
      const button = wrapper.findAll('button').find((candidate) => candidate.text() === label)
      expect(button).toBeDefined()
      await button!.trigger('click')
      await flushPromises()
      await button!.trigger('click')
      await flushPromises()
      const calls = vi.mocked(decideGenerationDefaultChange).mock.calls.filter(([, , receivedKey, , receivedAction]) => receivedKey === key && receivedAction === action)
      expect(calls).toHaveLength(2)
    }

    wrapper.unmount()
  })

  it('keeps a distinct historical fingerprint eligible for rollback', async () => {
    vi.mocked(fetchGenerationDefaults).mockResolvedValue({
      current: { provider_name: 'fake', model_version: 'fake-v1', prompt_version: 'generator-v1', prompt_template_fingerprint: 'new-fingerprint' },
      pending: [],
      history: [{ id: 'prior-1', status: 'superseded', provider_name: 'fake', model_version: 'fake-v1', prompt_version: 'generator-v1', prompt_template_fingerprint: 'old-fingerprint', request_reason: 'Prior prompt' }],
    })
    const wrapper = mount({ components: { AdminPage }, template: '<Suspense><AdminPage /></Suspense>' }, {
      global: { stubs: { LogoutButton: true, NuxtLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('申请回滚')
    wrapper.unmount()
  })
})
