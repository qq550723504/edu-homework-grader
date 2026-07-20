import { getHeader } from 'h3'

import { loadCorePrincipal } from '../../utils/core-api'
import { useAuthSession } from '../../utils/auth-session'

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event)
  if (config.appEnv !== 'e2e') {
    throw createError({ statusCode: 404, statusMessage: 'resource not found' })
  }
  const token = getHeader(event, 'x-e2e-token')
  if (!token) {
    throw createError({ statusCode: 401, statusMessage: 'authentication required' })
  }
  const principal = await loadCorePrincipal(event, token)
  const session = await useAuthSession(event)
  await session.update({
    csrfToken: crypto.randomUUID(),
    principal,
    tokens: { accessToken: token, expiresAt: Date.now() + 5 * 60_000 }
  })
  return principal
})
