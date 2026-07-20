export interface StudentAssignment {
  id: string
  title: string
  subject: string
  due_at: string
  status: string
}

export interface StudentAssignmentGroups {
  pending: StudentAssignment[]
  correction_required: StudentAssignment[]
  completed: StudentAssignment[]
}

export function studentAssignmentStatusLabel(status: string): string {
  return {
    pending: '待完成',
    overdue: '已逾期',
    late_allowed: '允许迟交',
    submitted_pending_review: '待复核',
    correction_required: '待订正',
    completed: '已完成'
  }[status] ?? status
}

export interface CurrentPrincipal {
  id: string
  tenant_id: string
  csrf_token?: string
}

type Request<T> = (url: string) => Promise<T>

export function publishedFeedback(detail: { grading?: Array<{ feedback?: Array<{ message?: string }> }> }): string[] {
  return (detail.grading ?? []).flatMap((run) => (run.feedback ?? [])
    .flatMap((entry) => typeof entry.message === 'string' ? [entry.message] : []))
}

export function correctionAvailable(detail: { corrections?: Array<{ status?: string }> }): boolean {
  return (detail.corrections ?? []).some((entry) => entry.status === 'published')
}

export function fetchStudentAssignments(request: Request<StudentAssignmentGroups>): Promise<StudentAssignmentGroups> {
  return request('/api/core/v1/student/assignments')
}

export function fetchCurrentPrincipal(request: Request<CurrentPrincipal>): Promise<CurrentPrincipal> {
  return request('/api/auth/session')
}
