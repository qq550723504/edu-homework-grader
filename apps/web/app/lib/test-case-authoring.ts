export type TestAnswerDraft = {
  advanced: boolean
  text: string
  json: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function textAnswerEnvelope(text: string): Record<string, unknown> {
  return { format: 'text-v1', text }
}

export function testAnswerFromDraft(draft: TestAnswerDraft): Record<string, unknown> {
  if (!draft.advanced) return textAnswerEnvelope(draft.text)

  try {
    const answer = JSON.parse(draft.json) as unknown
    if (!isRecord(answer)) throw new Error()
    return answer
  } catch {
    throw new Error('高级答案 JSON 格式无效。')
  }
}

export function testAnswerDraftFromAnswer(answer: Record<string, unknown>): TestAnswerDraft {
  if (answer.format === 'text-v1' && typeof answer.text === 'string') {
    return { advanced: false, text: answer.text, json: JSON.stringify(answer) }
  }
  return { advanced: true, text: '', json: JSON.stringify(answer) }
}

export function testAnswerFingerprint(answer: Record<string, unknown>): string {
  return JSON.stringify(answer)
}

export function isCurrentTestCasePreview(
  previewedVersionId: string,
  selectedVersionId: string | null,
  previewedAnswerFingerprint: string,
  currentAnswerFingerprint: string,
): boolean {
  return Boolean(previewedVersionId)
    && previewedVersionId === selectedVersionId
    && Boolean(previewedAnswerFingerprint)
    && previewedAnswerFingerprint === currentAnswerFingerprint
}
