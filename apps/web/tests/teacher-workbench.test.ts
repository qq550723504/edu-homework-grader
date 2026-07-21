import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  getTeacherModule,
  isAssignmentDraftReady,
  isQuestionDraftReady,
  teacherModules
} from '../app/lib/teacher-workbench'

describe('teacher workbench UI contract', () => {
  it('mounts the workbench navigation and live workspace modules on the teacher route', () => {
    const teacherPage = readFileSync(new URL('../app/pages/teacher/index.vue', import.meta.url), 'utf8')
    const overview = readFileSync(new URL('../app/components/teacher/TeacherOverview.vue', import.meta.url), 'utf8')
    const navigation = readFileSync(new URL('../app/components/teacher/TeacherWorkbenchNav.vue', import.meta.url), 'utf8')

    expect(teacherPage).toContain('<TeacherWorkbenchNav')
    expect(teacherPage).toContain('<TeacherOverview')
    expect(teacherPage).toContain('<TeacherQuestionWorkspace')
    expect(teacherPage).toContain('<TeacherAssignmentWorkspace')
    expect(teacherPage).toContain("activeModule === 'roster'")
    expect(teacherPage).toContain("watch(() => route.hash, syncModuleFromHash, { immediate: true })")
    expect(teacherPage).not.toContain("addEventListener('hashchange'")
    expect(teacherPage).toContain(':review-count="reviewCount"')
    expect(teacherPage).toContain('aria-label="作业学科"')
    expect(teacherPage).toContain('作业题目编排')
    expect(teacherPage).toContain('student-preview-heading')
    expect(teacherPage).toContain('question_version_ids')
    expect(teacherPage).toContain('updateAssignment')
    expect(teacherPage).not.toContain('addAssignmentItem')
    expect(overview).toContain('reviewCount: number')
    expect(overview).toContain("emit('open-module', 'roster')")
    expect(overview).not.toContain("value: '36'")
    expect(navigation).toContain("module === 'reviews'")
    expect(navigation).toContain("return '/teacher/reviews'")
  })

  it('exposes the six stable teacher modules in navigation order', () => {
    expect(teacherModules.map((module) => module.id)).toEqual([
      'overview', 'reviews', 'questions', 'assignments', 'roster', 'requests'
    ])
  })

  it('requires the visible question creation fields', () => {
    expect(isQuestionDraftReady({ title: '', prompt: '计算 2 + 3', questionType: 'math', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '   ', questionType: 'math', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '计算 2 + 3', questionType: '', answer: '5' })).toBe(false)
    expect(isQuestionDraftReady({ title: '加法练习', prompt: '计算 2 + 3', questionType: 'math', answer: '5' })).toBe(true)
  })

  it('guides English question authoring and keeps raw JSON behind an explicit advanced mode', () => {
    const teacherPage = readFileSync(new URL('../app/pages/teacher/index.vue', import.meta.url), 'utf8')

    expect(teacherPage).toContain('可接受答案')
    expect(teacherPage).toContain('词元')
    expect(teacherPage).toContain('启用语法反馈')
    expect(teacherPage).toContain('评分点')
    expect(teacherPage).toContain('高级 JSON 模式')
    expect(teacherPage).toContain('fetchQuestionPolicyCatalog')
    expect(teacherPage).toContain('buildEnglishQuestionRule')
  })

  it('requires the visible assignment creation fields', () => {
    expect(isAssignmentDraftReady({ title: '周末练习', className: '', dueAt: '2026-07-21T18:00', allowLate: false })).toBe(false)
    expect(isAssignmentDraftReady({ title: '周末练习', className: '三年级 2 班', dueAt: '', allowLate: false })).toBe(false)
    expect(isAssignmentDraftReady({ title: '周末练习', className: '三年级 2 班', dueAt: '2026-07-21T18:00', allowLate: true })).toBe(true)
  })

  it('resolves overview actions to a visible navigation module without sample queue counts', () => {
    expect(getTeacherModule('reviews')).toMatchObject({ label: '复核队列' })
    expect(getTeacherModule('questions')).toMatchObject({ label: '题库' })
    expect(getTeacherModule('assignments')).toMatchObject({ label: '作业' })
    expect(getTeacherModule('requests')).toMatchObject({ label: '学生申请' })
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
