import { describe, expect, it, vi } from 'vitest'

import {
  decideGenerationDefaultChange,
  fetchGenerationDefaults,
  rollbackGenerationDefaultChange,
  submitGenerationDefaultChange,
} from '../app/lib/admin-generation-defaults'

describe('admin generation default governance API', () => {
  it('keeps governance mutations on the same-origin BFF with CSRF and idempotency protection', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'change-1' })
    const report = { candidate: { provider_name: 'openai', model_version: 'gpt-4.1-2025-04-14', prompt_version: 'generator-v1' } }

    await submitGenerationDefaultChange(request, 'csrf-token', 'request-key', {
      provider_name: 'openai', model_version: 'gpt-4.1-2025-04-14', prompt_version: 'generator-v1',
      request_reason: '本周评估通过', evaluation_report: report,
    })
    await decideGenerationDefaultChange(request, 'csrf-token', 'change-1', 'approve', '双人复核通过')
    await decideGenerationDefaultChange(request, 'csrf-token', 'change-1', 'apply', '切换默认配置')
    await rollbackGenerationDefaultChange(request, 'csrf-token', 'rollback-key', 'change-1', '质量回退')

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/admin/ai-generation-default-change-requests', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token', 'Idempotency-Key': 'request-key' },
      body: {
        provider_name: 'openai', model_version: 'gpt-4.1-2025-04-14', prompt_version: 'generator-v1',
        request_reason: '本周评估通过', evaluation_report: report,
      },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/admin/ai-generation-default-change-requests/change-1/approve', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { reason: '双人复核通过' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/api/core/v1/admin/ai-generation-default-change-requests/change-1/apply', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { reason: '切换默认配置' },
    })
    expect(request).toHaveBeenNthCalledWith(4, '/api/core/v1/admin/ai-generation-default-change-requests/change-1/rollback', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token', 'Idempotency-Key': 'rollback-key' }, body: { reason: '质量回退' },
    })
  })

  it('loads the summary through the same-origin BFF without exposing provider credentials', async () => {
    const request = vi.fn().mockResolvedValue({ current: null, pending: [], history: [] })

    await expect(fetchGenerationDefaults(request)).resolves.toEqual({ current: null, pending: [], history: [] })
    expect(request).toHaveBeenCalledWith('/api/core/v1/admin/ai-generation-defaults')
  })
})
