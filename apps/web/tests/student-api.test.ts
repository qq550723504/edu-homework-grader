import { describe, expect, it, vi } from 'vitest'

import { fetchStudentAssignments } from '../app/lib/student-api'

describe('student assignment API', () => {
  it('sends the future login token to the student assignment endpoint', async () => {
    const request = vi.fn().mockResolvedValue({ pending: [], correction_required: [], completed: [] })

    await fetchStudentAssignments('https://api.example.test', 'short-lived-token', request)

    expect(request).toHaveBeenCalledWith('https://api.example.test/v1/student/assignments', {
      headers: { Authorization: 'Bearer short-lived-token' }
    })
  })
})
