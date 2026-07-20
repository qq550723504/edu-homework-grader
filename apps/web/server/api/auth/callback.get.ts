import { hasRequiredRole, roleHome } from '../../../app/lib/auth-routing'
import { loadCorePrincipal } from '../../utils/core-api'
import { discoverOpenIdConfiguration, exchangeAuthorizationCode } from '../../utils/oidc'
import { useAuthSession } from '../../utils/auth-session'

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event)
  const session = await useAuthSession(event)
  const login = session.data.login
  if (!login) {
    throw createError({ statusCode: 400, statusMessage: 'missing or expired login transaction' })
  }

  try {
    const allowInsecure = config.appEnv !== 'production'
    const authorizationServer = await discoverOpenIdConfiguration(config.oidcIssuer, allowInsecure)
    const redirectUri = new URL('/api/auth/callback', getRequestURL(event).origin).toString()
    const tokens = await exchangeAuthorizationCode({
      authorizationServer,
      callbackUrl: getRequestURL(event),
      clientId: config.oidcClientId,
      codeVerifier: login.codeVerifier,
      expectedNonce: login.nonce,
      expectedState: login.state,
      redirectUri,
      allowInsecure
    })
    const principal = await loadCorePrincipal(event, tokens.access_token)
    await session.update({
      csrfToken: crypto.randomUUID(),
      login: undefined,
      principal,
      tokens: {
        accessToken: tokens.access_token,
        expiresAt: Date.now() + (tokens.expires_in ?? 300) * 1000,
        refreshToken: tokens.refresh_token
      }
    })
    return sendRedirect(
      event,
      hasRequiredRole(principal.role, login.returnTo) ? login.returnTo : roleHome(principal.role)
    )
  } catch (error) {
    await session.clear()
    throw error
  }
})
