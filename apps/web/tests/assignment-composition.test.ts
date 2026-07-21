import { describe, expect, it } from 'vitest'

import {
  addQuestionToComposition,
  availableQuestionsForSubject,
  compositionSummary,
  moveQuestion,
  removeQuestion,
} from '../app/lib/assignment-composition'
import type { TeacherQuestionVersion } from '../app/lib/teacher-api'

const m1: TeacherQuestionVersion = {
  id: 'm1', question_id: 'question-m1', title: 'Addition', prompt: 'What is 2 + 3?',
  question_type: 'M1', policy_version: '1', status: 'published', max_score: 1,
}
const m2: TeacherQuestionVersion = {
  id: 'm2', question_id: 'question-m2', title: 'Expand', prompt: 'Expand (x + 1)^2.',
  question_type: 'M2', policy_version: '2', status: 'published', max_score: 2,
}
const e1: TeacherQuestionVersion = {
  id: 'e1', question_id: 'question-e1', title: 'Vocabulary', prompt: 'Choose the word.',
  question_type: 'E1', policy_version: '1', status: 'published', max_score: 1,
}
const draftM1 = { ...m1, id: 'draft-m1', status: 'draft' }

describe('assignment composition', () => {
  it('keeps one ordered published question for the selected subject', () => {
    expect(availableQuestionsForSubject([m1, m2, e1, draftM1], 'mathematics')).toEqual([m1, m2])
    expect(addQuestionToComposition([], m1, 'mathematics')).toEqual([m1])
    expect(addQuestionToComposition([m1], m1, 'mathematics')).toEqual([m1])
    expect(addQuestionToComposition([m1], e1, 'mathematics')).toEqual([m1])
  })

  it('moves, removes, and summarizes the ordered composition', () => {
    expect(moveQuestion([m1, m2], 1, -1)).toEqual([m2, m1])
    expect(moveQuestion([m1, m2], 0, -1)).toEqual([m1, m2])
    expect(removeQuestion([m1, m2], 'm1')).toEqual([m2])
    expect(compositionSummary([m1, m2])).toEqual({
      count: 2,
      totalScore: 3,
      types: { M1: 1, M2: 1 },
    })
  })
})
