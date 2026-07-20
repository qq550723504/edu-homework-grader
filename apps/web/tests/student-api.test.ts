import { describe, expect, it, vi } from 'vitest'

import { fetchCurrentPrincipal, fetchStudentAssignments, studentAssignmentStatusLabel } from '../app/lib/student-api'

describe('student assignment API', () => {
  it('uses the same-origin BFF proxy instead of exposing a bearer token', async () => {
    const request = vi.fn().mockResolvedValue({ pending: [], correction_required: [], completed: [] })

    await fetchStudentAssignments(request)

    expect(request).toHaveBeenCalledWith('/api/core/v1/student/assignments')
  })

  it('retrieves the API-confirmed principal from the protected session endpoint', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'student-1', tenant_id: 'tenant-1' })

    await expect(fetchCurrentPrincipal(request))
      .resolves.toEqual({ id: 'student-1', tenant_id: 'tenant-1' })

    expect(request).toHaveBeenCalledWith('/api/auth/session')
  })

  it('labels student-visible assignment states explicitly', () => {
    expect(studentAssignmentStatusLabel('submitted_pending_review')).toBe('待复核')
    expect(studentAssignmentStatusLabel('correction_required')).toBe('待订正')
    expect(studentAssignmentStatusLabel('overdue')).toBe('已逾期')
    expect(studentAssignmentStatusLabel('late_allowed')).toBe('允许迟交')
  })
})
