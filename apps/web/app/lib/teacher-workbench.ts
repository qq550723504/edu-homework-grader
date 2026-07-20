export type TeacherModule = 'overview' | 'reviews' | 'questions' | 'assignments' | 'requests'

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
  { id: 'reviews', label: '复核队列', badge: '36' },
  { id: 'questions', label: '题库' },
  { id: 'assignments', label: '作业' },
  { id: 'requests', label: '学生申请', badge: '2' }
]

export function isQuestionDraftReady(draft: QuestionDraft): boolean {
  return [draft.title, draft.prompt, draft.questionType, draft.answer].every((value) => value.trim().length > 0)
}

export function isAssignmentDraftReady(draft: AssignmentDraft): boolean {
  return [draft.title, draft.className, draft.dueAt].every((value) => value.trim().length > 0)
}
