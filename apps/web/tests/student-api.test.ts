import { describe, expect, it, vi } from 'vitest'

import { fetchCurrentPrincipal, fetchStudentAssignments } from '../app/lib/student-api'

describe('student assignment API', () => {
  it('sends the future login token to the student assignment endpoint', async () => {
    const request = vi.fn().mockResolvedValue({ pending: [], correction_required: [], completed: [] })

    await fetchStudentAssignments('https://api.example.test', 'short-lived-token', request)

    expect(request).toHaveBeenCalledWith('https://api.example.test/v1/student/assignments', {
      headers: { Authorization: 'Bearer short-lived-token' }
    })
  })

  it('retrieves the current principal before scoping local drafts', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'student-1', tenant_id: 'tenant-1' })

    await expect(fetchCurrentPrincipal('https://api.example.test', 'short-lived-token', request))
      .resolves.toEqual({ id: 'student-1', tenant_id: 'tenant-1' })

    expect(request).toHaveBeenCalledWith('https://api.example.test/v1/me', {
      headers: { Authorization: 'Bearer short-lived-token' }
    })
  })
})
