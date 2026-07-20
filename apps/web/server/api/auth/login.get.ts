import * as oauth from 'oauth4webapi'

import { allowedReturnPath } from '../../../app/lib/auth-routing'
import { buildAuthorizationUrl, discoverOpenIdConfiguration } from '../../utils/oidc'
import { useAuthSession } from '../../utils/auth-session'

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event)
  const session = await useAuthSession(event)
  const authorizationServer = await discoverOpenIdConfiguration(
    config.oidcIssuer,
    config.appEnv !== 'production'
  )
  if (!authorizationServer.authorization_endpoint) {
    throw createError({ statusCode: 502, statusMessage: 'OIDC issuer has no authorization endpoint' })
  }

  const codeVerifier = oauth.generateRandomCodeVerifier()
  const query = getQuery(event)
  const returnTo = allowedReturnPath(typeof query.returnTo === 'string' ? query.returnTo : undefined)
  const redirectUri = new URL('/api/auth/callback', getRequestURL(event).origin).toString()
  const state = crypto.randomUUID()
  const nonce = oauth.generateRandomNonce()
  await session.update({
    login: { codeVerifier, nonce, returnTo, state }
  })

  return sendRedirect(event, buildAuthorizationUrl(authorizationServer.authorization_endpoint, {
    clientId: config.oidcClientId,
    codeChallenge: await oauth.calculatePKCECodeChallenge(codeVerifier),
    nonce,
    redirectUri,
    state
  }))
})
