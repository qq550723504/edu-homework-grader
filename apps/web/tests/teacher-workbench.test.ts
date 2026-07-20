import { describe, expect, it } from 'vitest'

import {
  getTeacherModule,
  isAssignmentDraftReady,
  isQuestionDraftReady,
  teacherModules
} from '../app/lib/teacher-workbench'

describe('teacher workbench UI contract', () => {
  it('exposes the five stable teacher modules in navigation order', () => {
    expect(teacherModules.map((module) => module.id)).toEqual([
      'overview', 'reviews', 'questions', 'assignments', 'requests'
    ])
  })

  it('requires the visible question creation fields', () => {
    expect(isQuestionDraftReady({ title: '', prompt: '计算 2 + 3', questionType: 'math', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '   ', questionType: 'math', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '计算 2 + 3', questionType: '', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '计算 2 + 3', questionType: 'math', answer: '5' })).toBe(true)
  })

  it('requires the visible assignment creation fields', () => {
    expect(isAssignmentDraftReady({ title: '周末练习', className: '', dueAt: '2026-07-21T18:00', allowLate: false })).toBe(false)
    expect(isAssignmentDraftReady({ title: '周末练习', className: '三年级 2 班', dueAt: '', allowLate: false })).toBe(false)
    expect(isAssignmentDraftReady({ title: '周末练习', className: '三年级 2 班', dueAt: '2026-07-21T18:00', allowLate: true })).toBe(true)
  })

  it('resolves overview actions to a visible navigation module', () => {
    expect(getTeacherModule('reviews')).toMatchObject({ label: '复核队列', badge: '36' })
    expect(getTeacherModule('questions')).toMatchObject({ label: '题库' })
    expect(getTeacherModule('assignments')).toMatchObject({ label: '作业' })
    expect(getTeacherModule('requests')).toMatchObject({ label: '学生申请', badge: '2' })
  })

  it('rejects whitespace-only question answers', () => {
    expect(isQuestionDraftReady({
      title: '加法练习', prompt: '计算 2 + 3', questionType: 'math', answer: '   '
    })).toBe(false)
  })

  it('does not make late-submission choice a prerequisite for an assignment draft', () => {
    const base = { title: '周末练习', className: '三年级 2 班', dueAt: '2026-07-21T18:00' }
    expect(isAssignmentDraftReady({ ...base, allowLate: false })).toBe(true)
    expect(isAssignmentDraftReady({ ...base, allowLate: true })).toBe(true)
  })
})
