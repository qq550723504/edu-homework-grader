import type { H3Event } from 'h3'

import { createError } from 'h3'

import { discoverOpenIdConfiguration, refreshAccessToken } from './oidc'
import { sessionExpiresSoon, useAuthSession, type AuthPrincipal } from './auth-session'

function configFor(event: H3Event) {
  const config = useRuntimeConfig(event)
  return {
    coreApiBase: config.coreApiBase.replace(/\/$/, ''),
    appEnv: config.appEnv,
    oidcClientId: config.oidcClientId,
    oidcIssuer: config.oidcIssuer
  }
}

export async function currentPrincipal(event: H3Event): Promise<AuthPrincipal> {
  const session = await useAuthSession(event)
  const tokens = session.data.tokens
  if (!tokens || !session.data.principal) {
    throw createError({ statusCode: 401, statusMessage: 'authentication required' })
  }
  await refreshSessionIfNeeded(event)
  return (await useAuthSession(event)).data.principal!
}

export async function accessTokenForCoreApi(event: H3Event): Promise<string> {
  const session = await useAuthSession(event)
  if (!session.data.tokens) {
    throw createError({ statusCode: 401, statusMessage: 'authentication required' })
  }
  await refreshSessionIfNeeded(event)
  const refreshed = await useAuthSession(event)
  if (!refreshed.data.tokens) {
    throw createError({ statusCode: 401, statusMessage: 'authentication required' })
  }
  return refreshed.data.tokens.accessToken
}

export async function loadCorePrincipal(event: H3Event, accessToken: string): Promise<AuthPrincipal> {
  const { coreApiBase } = configFor(event)
  return $fetch<AuthPrincipal>(`${coreApiBase}/v1/me`, {
    headers: { authorization: `Bearer ${accessToken}` }
  })
}

async function refreshSessionIfNeeded(event: H3Event): Promise<void> {
  const session = await useAuthSession(event)
  const tokens = session.data.tokens
  if (!tokens || !sessionExpiresSoon(tokens.expiresAt)) return
  if (!tokens.refreshToken) {
    await session.clear()
    throw createError({ statusCode: 401, statusMessage: 'authentication expired' })
  }

  const { appEnv, oidcClientId, oidcIssuer } = configFor(event)
  try {
    const allowInsecure = appEnv !== 'production'
    const authorizationServer = await discoverOpenIdConfiguration(oidcIssuer, allowInsecure)
    const refreshed = await refreshAccessToken({
      authorizationServer,
      clientId: oidcClientId,
      refreshToken: tokens.refreshToken,
      allowInsecure
    })
    await session.update({
      tokens: {
        accessToken: refreshed.access_token,
        expiresAt: Date.now() + (refreshed.expires_in ?? 300) * 1000,
        refreshToken: refreshed.refresh_token ?? tokens.refreshToken
      }
    })
  } catch {
    await session.clear()
    throw createError({ statusCode: 401, statusMessage: 'authentication expired' })
  }
}
