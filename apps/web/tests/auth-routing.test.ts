import { describe, expect, it } from 'vitest'

import { allowedReturnPath, hasRequiredRole, roleHome } from '../app/lib/auth-routing'

describe('authentication route policy', () => {
  it('only retains a same-origin absolute-path return target', () => {
    expect(allowedReturnPath('/student/assignments/a-1?from=list')).toBe('/student/assignments/a-1?from=list')
    expect(allowedReturnPath('//attacker.example.test')).toBe('/')
    expect(allowedReturnPath('https://attacker.example.test')).toBe('/')
    expect(allowedReturnPath('student')).toBe('/')
  })

  it('maps the API-confirmed role to the only permitted workspace', () => {
    expect(roleHome('student')).toBe('/student')
    expect(roleHome('teacher')).toBe('/teacher')
    expect(roleHome('admin')).toBe('/admin')
    expect(hasRequiredRole('student', '/student/assignments/a-1')).toBe(true)
    expect(hasRequiredRole('student', '/teacher')).toBe(false)
    expect(hasRequiredRole('teacher', '/teacher')).toBe(true)
    expect(hasRequiredRole('admin', '/admin')).toBe(true)
  })
})
