export type TeacherModule = 'overview' | 'reviews' | 'ai_questions' | 'questions' | 'assignments' | 'roster' | 'requests'

export interface QuestionDraft {
  title: string
  prompt: string
  questionType: string
  answer: string
}

export interface AssignmentDraft {
  title: string
  className: string
  dueAt: string
  allowLate: boolean
}

export const teacherModules: ReadonlyArray<{ id: TeacherModule; label: string; badge?: string }> = [
  { id: 'overview', label: '工作台' },
  { id: 'reviews', label: '复核队列' },
  { id: 'ai_questions', label: 'AI 出题审核' },
  { id: 'questions', label: '题库' },
  { id: 'assignments', label: '作业' },
  { id: 'roster', label: '班级名册' },
  { id: 'requests', label: '学生申请' }
]

export function getTeacherModule(id: TeacherModule) {
  return teacherModules.find((module) => module.id === id)!
}

export function isQuestionDraftReady(draft: QuestionDraft): boolean {
  return [draft.title, draft.prompt, draft.questionType, draft.answer].every((value) => value.trim().length > 0)
}

export function isAssignmentDraftReady(draft: AssignmentDraft): boolean {
  return [draft.title, draft.className, draft.dueAt].every((value) => value.trim().length > 0)
}
