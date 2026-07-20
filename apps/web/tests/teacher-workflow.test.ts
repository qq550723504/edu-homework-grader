import { describe, expect, it } from 'vitest'

import { clearGuardianConsentEvidence, guardianConsentFieldsRequired, teacherErrorMessage } from '../app/lib/teacher-workflow'

describe('teacher workspace state', () => {
  it('shows guardian consent inputs only for students under fourteen', () => {
    expect(guardianConsentFieldsRequired(false)).toBe(false)
    expect(guardianConsentFieldsRequired(true)).toBe(true)
  })

  it('clears hidden guardian consent evidence unless consent is granted', () => {
    expect(clearGuardianConsentEvidence('pending', '2026-07', 'signed-form-1')).toEqual({
      noticeVersion: '',
      evidenceReference: '',
    })
    expect(clearGuardianConsentEvidence('withdrawn', '2026-07', 'signed-form-1')).toEqual({
      noticeVersion: '',
      evidenceReference: '',
    })
    expect(clearGuardianConsentEvidence('granted', '2026-07', 'signed-form-1')).toEqual({
      noticeVersion: '2026-07',
      evidenceReference: 'signed-form-1',
    })
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
