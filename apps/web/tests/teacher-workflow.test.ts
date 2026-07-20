import { describe, expect, it } from 'vitest'

import { guardianConsentFieldsRequired, teacherErrorMessage } from '../app/lib/teacher-workflow'

describe('teacher workspace state', () => {
  it('shows guardian consent inputs only for students under fourteen', () => {
    expect(guardianConsentFieldsRequired(false)).toBe(false)
    expect(guardianConsentFieldsRequired(true)).toBe(true)
  })

  it('prefers the API validation detail when an operation fails', () => {
    expect(teacherErrorMessage({ data: { detail: 'row 2 has an invalid student_under_14 value' } }))
      .toBe('row 2 has an invalid student_under_14 value')
  })

  it('uses a friendly fallback for unknown failures', () => {
    expect(teacherErrorMessage(new Error('network down')))
      .toBe('操作失败，请检查填写内容后重试。')
  })
})
