export type PlatformRole = 'student' | 'teacher' | 'admin'

const roleRoots: Record<PlatformRole, string> = {
  student: '/student',
  teacher: '/teacher',
  admin: '/admin'
}

export function allowedReturnPath(value: string | undefined): string {
  if (!value?.startsWith('/') || value.startsWith('//')) return '/'
  return value
}

export function roleHome(role: PlatformRole): string {
  return roleRoots[role]
}

export function hasRequiredRole(role: PlatformRole, path: string): boolean {
  return path === roleRoots[role] || path.startsWith(`${roleRoots[role]}/`)
}
