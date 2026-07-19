import { describe, expect, it } from 'vitest'

import { correctionAvailable, publishedFeedback } from '../app/lib/student-api'

describe('student assignment feedback projections', () => {
  it('returns messages only after the API supplies published grading', () => {
    expect(publishedFeedback({ grading: [] })).toEqual([])
    expect(publishedFeedback({ grading: [{ feedback: [{ message: '表达式等价。' }] }] }))
      .toEqual(['表达式等价。'])
  })

  it('reports correction availability only for published correction rows', () => {
    expect(correctionAvailable({ corrections: [] })).toBe(false)
    expect(correctionAvailable({ corrections: [{ status: 'published' }] })).toBe(true)
  })
})
