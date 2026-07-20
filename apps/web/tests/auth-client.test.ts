import { describe, expect, it, vi } from 'vitest'

import { logout } from '../app/lib/auth-client'

describe('web session logout', () => {
  it('clears the protected server session before removing local drafts', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ csrf_token: 'csrf-token' })
      .mockResolvedValueOnce({ ok: true })
    const clearDrafts = vi.fn().mockResolvedValue(undefined)

    await logout(request, clearDrafts)

    expect(request).toHaveBeenNthCalledWith(1, '/api/auth/session')
    expect(request).toHaveBeenNthCalledWith(2, '/api/auth/logout', {
      method: 'POST',
      headers: { 'X-CSRF-Token': 'csrf-token' }
    })
    expect(clearDrafts).toHaveBeenCalledOnce()
  })
})
