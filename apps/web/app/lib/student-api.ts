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

export interface CurrentPrincipal {
  id: string
  tenant_id: string
}

type Request<T> = (url: string, options: { headers: Record<string, string> }) => Promise<T>

export function fetchStudentAssignments(
  apiBase: string,
  token: string,
  request: Request<StudentAssignmentGroups>
): Promise<StudentAssignmentGroups> {
  return request(`${apiBase}/v1/student/assignments`, {
    headers: { Authorization: `Bearer ${token}` }
  })
}

export function fetchCurrentPrincipal(
  apiBase: string,
  token: string,
  request: Request<CurrentPrincipal>
): Promise<CurrentPrincipal> {
  return request(`${apiBase}/v1/me`, {
    headers: { Authorization: `Bearer ${token}` }
  })
}
