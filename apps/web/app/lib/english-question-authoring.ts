export type EnglishQuestionType = 'E1' | 'E2' | 'E3' | 'E4'

export interface EnglishScoringPointDraft {
  id: string
  evidencePhrases: string[]
  score: number
}

export interface EnglishQuestionDraft {
  acceptedAnswers: string[]
  lemma: string
  acceptedForms: string[]
  constraints: {
    partOfSpeech: string
    tense: string
    number: string
    determiner: string
  }
  grammarFeedbackRequired: boolean | null
  scoringPoints: EnglishScoringPointDraft[]
  similarityThreshold: number
  maxScore: number
}

export interface EnglishRuleBuildResult {
  rule?: Record<string, unknown>
  errors: Record<string, string>
}

const maxScoreError = '最高分必须是 0 到 100 之间的有限正数。'

export function defaultEnglishDraft(_questionType: EnglishQuestionType): EnglishQuestionDraft {
  return {
    acceptedAnswers: [''],
    lemma: '',
    acceptedForms: [''],
    constraints: { partOfSpeech: '', tense: '', number: '', determiner: '' },
    grammarFeedbackRequired: null,
    scoringPoints: [],
    similarityThreshold: 0.78,
    maxScore: 1,
  }
}

export function buildEnglishQuestionRule(
  questionType: EnglishQuestionType,
  draft: EnglishQuestionDraft,
): EnglishRuleBuildResult {
  const errors: Record<string, string> = {}
  const maxScore = validMaxScore(draft.maxScore, errors)
  if (questionType === 'E1') {
    const acceptedAnswers = requiredTexts(draft.acceptedAnswers, 'acceptedAnswers', '请至少填写一个可接受答案。', errors)
    if (Object.keys(errors).length) return { errors }
    return {
      rule: {
        accepted_answers: acceptedAnswers,
        normalization: {
          unicode_form: 'NFKC', collapse_whitespace: true, ignore_case: true, ignore_terminal_punctuation: true,
        },
        max_score: maxScore,
      },
      errors,
    }
  }
  if (questionType === 'E2') {
    const lemma = draft.lemma.trim()
    if (!lemma) errors.lemma = '请填写词元。'
    const acceptedForms = requiredTexts(draft.acceptedForms, 'acceptedForms', '请至少填写一个可接受词形。', errors)
    if (Object.keys(errors).length) return { errors }
    const constraints = Object.fromEntries(
      Object.entries(draft.constraints)
        .map(([key, value]) => [toSnakeCase(key), value.trim()])
        .filter(([, value]) => value),
    )
    return { rule: { lemma, accepted_forms: acceptedForms, constraints, max_score: maxScore }, errors }
  }
  if (questionType === 'E3') {
    if (draft.grammarFeedbackRequired === null) errors.grammarFeedbackRequired = '请选择是否启用语法反馈。'
    if (Object.keys(errors).length) return { errors }
    const acceptedAnswers = normalizedTexts(draft.acceptedAnswers)
    return {
      rule: {
        grammar_feedback_required: draft.grammarFeedbackRequired,
        ...(acceptedAnswers.length ? { accepted_answers: acceptedAnswers } : {}),
        max_score: maxScore,
      },
      errors,
    }
  }
  const scoringPoints = draft.scoringPoints.map((point, index) => {
    const id = point.id.trim()
    const evidencePhrases = normalizedTexts(point.evidencePhrases)
    if (!id) errors[`scoringPoints.${index}.id`] = '请填写评分点名称。'
    if (!evidencePhrases.length) errors[`scoringPoints.${index}.evidencePhrases`] = '请至少填写一个证据短语。'
    if (!isPositiveScore(point.score)) errors[`scoringPoints.${index}.score`] = maxScoreError
    return { id, evidence_phrases: evidencePhrases, score: point.score }
  })
  if (!scoringPoints.length) errors.scoringPoints = '请至少添加一个评分点。'
  if (!Number.isFinite(draft.similarityThreshold) || draft.similarityThreshold < 0 || draft.similarityThreshold > 1) {
    errors.similarityThreshold = '语义阈值必须是 0 到 1 之间的有限数字。'
  }
  if (Object.keys(errors).length) return { errors }
  return {
    rule: { scoring_points: scoringPoints, similarity_threshold: draft.similarityThreshold, max_score: maxScore },
    errors,
  }
}

export function fieldForPolicyError(path: string): string | null {
  if (path === '/') return null
  return path.split('/').filter(Boolean).map((segment) => ({
    accepted_answers: 'acceptedAnswers',
    accepted_forms: 'acceptedForms',
    grammar_feedback_required: 'grammarFeedbackRequired',
    scoring_points: 'scoringPoints',
    evidence_phrases: 'evidencePhrases',
    similarity_threshold: 'similarityThreshold',
    max_score: 'maxScore',
  }[segment] ?? segment)).join('.')
}

function requiredTexts(values: string[], field: string, message: string, errors: Record<string, string>): string[] {
  const texts = normalizedTexts(values)
  if (!texts.length) errors[field] = message
  return texts
}

function normalizedTexts(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}

function validMaxScore(value: number, errors: Record<string, string>): number {
  if (!isPositiveScore(value)) errors.maxScore = maxScoreError
  return value
}

function isPositiveScore(value: number): boolean {
  return Number.isFinite(value) && value > 0 && value <= 100
}

function toSnakeCase(value: string): string {
  return value.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
}
