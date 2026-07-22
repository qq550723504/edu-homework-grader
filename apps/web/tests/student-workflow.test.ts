import { describe, expect, it } from 'vitest'

import {
  editorStateForItem,
  getUnansweredCount,
  isAssignmentWritable,
  nextQuestionIndex,
  previousQuestionIndex
} from '../app/lib/student-workflow'

describe('student question workflow', () => {
  it('prevents edits only after a non-late overdue deadline', () => {
    expect(isAssignmentWritable('pending')).toBe(true)
    expect(isAssignmentWritable('late_allowed')).toBe(true)
    expect(isAssignmentWritable('overdue')).toBe(false)
    expect(isAssignmentWritable('submitted_pending_review')).toBe(false)
  })

  it('keeps navigation in range and counts unanswered items', () => {
    expect(previousQuestionIndex(0)).toBe(0)
    expect(nextQuestionIndex(1, 2)).toBe(1)
    expect(nextQuestionIndex(0, 2)).toBe(1)
    expect(getUnansweredCount([
      { answer: null },
      { answer: { format: 'text-v1', text: '5' } },
      { answer: { format: 'text-v1', text: '' } },
    ])).toBe(2)
  })

  it('counts a structured MathJSON response as answered', () => {
    expect(getUnansweredCount([
      { answer: { format: 'mathjson-v1', latex: 'x+1', mathjson: ['Add', 'x', 1] } },
      { answer: { format: 'mathjson-v1', latex: ' ', mathjson: ['Add', 'x', 1] } },
      { answer: { format: 'mathjson-v1', latex: 'x+1', mathjson: null } }
    ])).toBe(2)
  })

  it('loads each item into an isolated editor state when switching questions', () => {
    expect(editorStateForItem({ answer: { format: 'text-v1', text: 'first answer' } })).toEqual({
      text: 'first answer',
      mathAnswer: null
    })
    expect(editorStateForItem({
      answer: { format: 'mathjson-v1', latex: 'x+1', mathjson: ['Add', 'x', 1] }
    })).toEqual({
      text: '',
      mathAnswer: { format: 'mathjson-v1', latex: 'x+1', mathjson: ['Add', 'x', 1] }
    })
  })
})
