import type { TeacherAiDraft, TeacherAiValidationRun } from './teacher-ai-review'

export type TeacherAiReviewPresentationKind =
  | 'needs_fix' | 'needs_confirmation' | 'ready' | 'accepted' | 'rejected' | 'waiting'

export interface TeacherAiReviewPresentation {
  kind: TeacherAiReviewPresentationKind
  label: string
  title: string
  description: string
  primaryAction: string | null
}

export function reviewPresentation(
  draft: TeacherAiDraft,
  validation: TeacherAiValidationRun | null,
): TeacherAiReviewPresentation {
  if (draft.teacher_state === 'accepted') return {
    kind: 'accepted', label: '已接受', title: '已创建题库草稿',
    description: '题目尚未发布给学生；请在题库中组卷后再发布作业。', primaryAction: null,
  }
  if (draft.teacher_state === 'rejected') return {
    kind: 'rejected', label: '已拒绝', title: '已拒绝这道候选题',
    description: '该候选题不会进入题库。', primaryAction: null,
  }
  if (!validation) return {
    kind: 'waiting', label: '待校验', title: '正在等待系统校验',
    description: '校验结果返回前不能接受这道题。', primaryAction: null,
  }
  if (validation.status === 'blocked') return {
    kind: 'needs_fix', label: '需修正', title: '暂不能接受',
    description: validation.findings[0]?.remediation ?? '请修正题目后重新校验，或重新生成、拒绝这道题。',
    primaryAction: '修改并重新校验',
  }
  if (validation.status === 'warning') return {
    kind: 'needs_confirmation', label: '需确认', title: '需要教师确认',
    description: validation.findings[0]?.remediation ?? '请阅读系统提醒后决定是否接受。',
    primaryAction: '已阅读后接受为题库草稿',
  }
  return {
    kind: 'ready', label: '可以接受', title: '可以接受',
    description: '已通过系统校验；接受后只会创建题库草稿。', primaryAction: '接受为题库草稿',
  }
}
