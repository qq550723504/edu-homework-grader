import { describe, expect, it } from 'vitest'

import { isCurrentTestCasePreview, isTestCasePreviewSnapshotCurrent, normalizeTestCaseCategory, testAnswerDraftFromAnswer, testAnswerFingerprint, testAnswerFromDraft } from '../app/lib/test-case-authoring'

describe('test case authoring', () => {
  it('builds the text-v1 answer envelope from the teacher-facing answer field', () => {
    expect(testAnswerFromDraft({ advanced: false, text: '4', json: '' })).toEqual({
      format: 'text-v1', text: '4',
    })
  })

  it('uses advanced JSON only when the author explicitly enables it', () => {
    const answer = testAnswerFromDraft({
      advanced: true,
      text: '',
      json: '{"mathjson":["Add","x",1],"variables":["x"]}',
    })

    expect(answer).toEqual({ mathjson: ['Add', 'x', 1], variables: ['x'] })
    expect(testAnswerFingerprint(answer)).toBe('{"mathjson":["Add","x",1],"variables":["x"]}')
  })

  it('returns text-v1 answers to the simple authoring mode', () => {
    expect(testAnswerDraftFromAnswer({ format: 'text-v1', text: 'cat' })).toMatchObject({
      advanced: false, text: 'cat',
    })
  })

  it('keeps non-text protocols in the explicit advanced mode', () => {
    expect(testAnswerDraftFromAnswer({ mathjson: ['Add', 'x', 1] })).toMatchObject({
      advanced: true,
      json: '{"mathjson":["Add","x",1]}',
    })
  })

  it('rejects malformed advanced JSON before making a request', () => {
    expect(() => testAnswerFromDraft({ advanced: true, text: '', json: '{bad json' })).toThrow(
      '高级答案 JSON 格式无效。',
    )
  })

  it('requires a preview to match both the current version and answer', () => {
    expect(isCurrentTestCasePreview('version-a', 'version-a', 'answer-a', 'answer-a')).toBe(true)
    expect(isCurrentTestCasePreview('version-a', 'version-b', 'answer-a', 'answer-a')).toBe(false)
    expect(isCurrentTestCasePreview('version-a', 'version-a', 'answer-a', 'answer-b')).toBe(false)
  })

  it('invalidates a captured preview when the author changes versions while submitting', () => {
    expect(isTestCasePreviewSnapshotCurrent(
      { versionId: 'version-a', answerFingerprint: 'answer-a', generation: 1 },
      { versionId: 'version-a', answerFingerprint: 'answer-a', generation: 1 },
    )).toBe(true)
    expect(isTestCasePreviewSnapshotCurrent(
      { versionId: 'version-a', answerFingerprint: 'answer-a', generation: 1 },
      { versionId: 'version-b', answerFingerprint: '', generation: 2 },
    )).toBe(false)
  })

  it('resets categories that the selected question policy does not support', () => {
    expect(normalizeTestCaseCategory('invalid_mathjson', 'M2', '2')).toBe('invalid_mathjson')
    expect(normalizeTestCaseCategory('invalid_mathjson', 'M2', '1')).toBe('correct')
    expect(normalizeTestCaseCategory('invalid_ast', 'E1', '1')).toBe('correct')
  })
})
