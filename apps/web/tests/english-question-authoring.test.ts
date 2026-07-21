import { describe, expect, it } from 'vitest'

import { buildEnglishQuestionRule, defaultEnglishDraft, fieldForPolicyError } from '../app/lib/english-question-authoring'

describe('guided English question authoring', () => {
  it('creates an E4@2-compatible rule from scoring point fields', () => {
    const draft = defaultEnglishDraft('E4')
    draft.scoringPoints = [{ id: 'cause', evidencePhrases: [' bridge closed ', 'bridge closed'], score: 1 }]

    expect(buildEnglishQuestionRule('E4', draft)).toEqual({
      rule: {
        scoring_points: [{ id: 'cause', evidence_phrases: ['bridge closed'], score: 1 }],
        similarity_threshold: 0.78,
        max_score: 1,
      },
      errors: {},
    })
  })

  it('requires the English fields mandated by each policy', () => {
    const e1 = defaultEnglishDraft('E1')
    const e2 = defaultEnglishDraft('E2')
    const e3 = defaultEnglishDraft('E3')
    const e4 = defaultEnglishDraft('E4')

    expect(buildEnglishQuestionRule('E1', e1).errors).toMatchObject({ acceptedAnswers: expect.any(String) })
    expect(buildEnglishQuestionRule('E2', e2).errors).toMatchObject({
      lemma: expect.any(String), acceptedForms: expect.any(String),
    })
    expect(buildEnglishQuestionRule('E3', e3).errors).toMatchObject({ grammarFeedbackRequired: expect.any(String) })
    expect(buildEnglishQuestionRule('E4', e4).errors).toMatchObject({ scoringPoints: expect.any(String) })
  })

  it('rejects non-finite and out-of-range numeric fields', () => {
    const e1 = defaultEnglishDraft('E1')
    e1.acceptedAnswers = ['cat']
    e1.maxScore = Number.POSITIVE_INFINITY
    const e4 = defaultEnglishDraft('E4')
    e4.scoringPoints = [{ id: 'cause', evidencePhrases: ['bridge closed'], score: 1 }]
    e4.similarityThreshold = 1.1

    expect(buildEnglishQuestionRule('E1', e1).errors).toMatchObject({ maxScore: expect.any(String) })
    expect(buildEnglishQuestionRule('E4', e4).errors).toMatchObject({ similarityThreshold: expect.any(String) })
  })

  it('maps API JSON Pointers to the form field keys', () => {
    expect(fieldForPolicyError('/scoring_points/0/evidence_phrases')).toBe('scoringPoints.0.evidencePhrases')
    expect(fieldForPolicyError('/normalization')).toBe('normalization')
    expect(fieldForPolicyError('/')).toBeNull()
  })
})
