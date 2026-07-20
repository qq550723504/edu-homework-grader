import type { H3Event } from 'h3'

import { getHeader } from 'h3'

import { useAuthSession } from './auth-session'

export async function requireCsrfToken(event: H3Event): Promise<void> {
  const session = await useAuthSession(event)
  const provided = getHeader(event, 'x-csrf-token')
  if (!session.data.csrfToken || provided !== session.data.csrfToken) {
    throw createError({ statusCode: 403, statusMessage: 'invalid CSRF token' })
  }
}
