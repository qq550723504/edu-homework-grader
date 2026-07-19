import { describe, expect, it } from 'vitest'

import { getUnansweredCount, nextQuestionIndex, previousQuestionIndex } from '../app/lib/student-workflow'

describe('student question workflow', () => {
  it('keeps navigation in range and counts unanswered items', () => {
    expect(previousQuestionIndex(0)).toBe(0)
    expect(nextQuestionIndex(1, 2)).toBe(1)
    expect(nextQuestionIndex(0, 2)).toBe(1)
    expect(getUnansweredCount([{ answer: null }, { answer: { value: '5' } }, { answer: { value: '' } }])).toBe(2)
  })

  it('counts a structured MathJSON response as answered', () => {
    expect(getUnansweredCount([
      { answer: { format: 'mathjson-v1', latex: 'x+1', mathjson: ['Add', 'x', 1] } },
      { answer: { format: 'mathjson-v1', latex: ' ', mathjson: ['Add', 'x', 1] } },
      { answer: { format: 'mathjson-v1', latex: 'x+1', mathjson: null } }
    ])).toBe(2)
  })
})
