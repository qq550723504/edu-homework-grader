import { hasRequiredRole, type PlatformRole } from '../lib/auth-routing'

export default defineNuxtRouteMiddleware(async (to) => {
  if (!['/student', '/teacher', '/admin'].some((prefix) => to.path === prefix || to.path.startsWith(`${prefix}/`))) {
    return
  }

  const request = import.meta.server ? useRequestFetch() : $fetch
  const principal = await request<{ role: PlatformRole } | null>('/api/auth/session')
  if (!principal) {
    return navigateTo(`/api/auth/login?returnTo=${encodeURIComponent(to.fullPath)}`, { external: true })
  }
  if (!hasRequiredRole(principal.role, to.path)) {
    throw createError({ statusCode: 404, statusMessage: 'page not found' })
  }
})
