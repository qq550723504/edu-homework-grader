import { describe, expect, it } from 'vitest'

import {
  candidateEditInput,
  type TeacherAiCandidate,
} from '../app/lib/teacher-ai-review'


describe('teacher AI verification assertions', () => {
  it('synchronizes an edited M1 rule, score, and explanation conclusion', () => {
    const candidate: TeacherAiCandidate = {
      objective_revision_id: 'objective-1',
      question_type: 'M1',
      policy_version: '1',
      prompt: 'What is 2 + 2?',
      rule_json: { expected: 4, tolerance: 0 },
      explanation: 'Add the numbers. Final answer: 4',
      knowledge_point: 'addition',
      difficulty: 0.2,
      verification_assertions: {
        final_answer_text: '4',
        final_answer_mathjson: null,
        declared_max_score: 1,
      },
      reading_material: null,
    }

    const updated = candidateEditInput(candidate, {
      rule_json: { expected: 5, tolerance: 0 },
      explanation: 'Use the corrected arithmetic.',
    })

    expect(updated.verification_assertions).toEqual({
      final_answer_text: '5',
      final_answer_mathjson: null,
      declared_max_score: 1,
    })
    expect(updated.explanation).toBe('Use the corrected arithmetic.\n\nFinal answer: 5')
  })

  it('synchronizes an edited M2 MathJSON answer and maximum score', () => {
    const candidate: TeacherAiCandidate = {
      objective_revision_id: 'objective-2',
      question_type: 'M2',
      policy_version: '2',
      prompt: 'Simplify the expression.',
      rule_json: {
        expected: ['Add', 'x', 1],
        variables: ['x'],
        max_score: 4,
      },
      explanation: 'Combine like terms. Final answer: x + 1',
      knowledge_point: 'algebra',
      difficulty: 0.4,
      verification_assertions: {
        final_answer_text: 'x + 1',
        final_answer_mathjson: '["Add","x",1]',
        declared_max_score: 4,
      },
      reading_material: null,
    }

    const expected = ['Multiply', 2, 'x']
    const updated = candidateEditInput(candidate, {
      rule_json: {
        expected,
        variables: ['x'],
        max_score: 6,
      },
      explanation: 'Apply the multiplication rule.',
    })

    expect(updated.verification_assertions).toEqual({
      final_answer_text: '["Multiply",2,"x"]',
      final_answer_mathjson: '["Multiply",2,"x"]',
      declared_max_score: 6,
    })
    expect(updated.explanation).toBe(
      'Apply the multiplication rule.\n\nFinal answer: ["Multiply",2,"x"]',
    )
  })
})
