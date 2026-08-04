export type TestAnswerDraft = {
  advanced: boolean
  text: string
  json: string
}

export type TestCasePreviewSnapshot = {
  versionId: string | null
  answerFingerprint: string
  generation: number
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

export function isTestCasePreviewSnapshotCurrent(
  snapshot: TestCasePreviewSnapshot,
  current: TestCasePreviewSnapshot,
): boolean {
  return Boolean(snapshot.versionId)
    && snapshot.versionId === current.versionId
    && snapshot.answerFingerprint === current.answerFingerprint
    && snapshot.generation === current.generation
}

export function normalizeTestCaseCategory(
  category: string,
  questionType: string | undefined,
  policyVersion: string | undefined,
): string {
  const supported = new Set(['correct', 'incorrect', 'empty', 'boundary'])
  if (questionType === 'M2') {
    supported.add('invalid_ast')
    if (policyVersion === '2') {
      supported.add('invalid_mathjson')
      supported.add('resource_limit')
    }
  }
  if (questionType === 'E3') supported.add('grammar_feedback')
  if (questionType === 'E4') supported.add('needs_review')
  return supported.has(category) ? category : 'correct'
}
