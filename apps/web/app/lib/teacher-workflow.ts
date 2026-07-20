export function guardianConsentFieldsRequired(under14: boolean): boolean {
  return under14
}

export function clearGuardianConsentEvidence(
  status: 'not_required' | 'pending' | 'granted' | 'withdrawn',
  noticeVersion: string,
  evidenceReference: string,
): { noticeVersion: string; evidenceReference: string } {
  if (status === 'granted') return { noticeVersion, evidenceReference }
  return { noticeVersion: '', evidenceReference: '' }
}

export function teacherErrorMessage(error: unknown): string {
  if (
    typeof error === 'object'
    && error !== null
    && 'data' in error
    && typeof error.data === 'object'
    && error.data !== null
    && 'detail' in error.data
    && typeof error.data.detail === 'string'
  ) {
    return error.data.detail
  }
  return '操作失败，请检查填写内容后重试。'
}
