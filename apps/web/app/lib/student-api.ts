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

type Request = (url: string, options: { headers: Record<string, string> }) => Promise<StudentAssignmentGroups>

export function fetchStudentAssignments(
  apiBase: string,
  token: string,
  request: Request
): Promise<StudentAssignmentGroups> {
  return request(`${apiBase}/v1/student/assignments`, {
    headers: { Authorization: `Bearer ${token}` }
  })
}
