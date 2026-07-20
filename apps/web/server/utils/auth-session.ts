import type { H3Event } from 'h3'

import type { PlatformRole } from '../../app/lib/auth-routing'

export interface AuthPrincipal {
  id: string
  tenant_id: string
  role: PlatformRole
  school_id: string | null
  display_name: string
}

interface LoginTransaction {
  codeVerifier: string
  nonce: string
  returnTo: string
  state: string
}

interface TokenSet {
  accessToken: string
  expiresAt: number
  refreshToken?: string
}

export interface AuthSessionData {
  csrfToken?: string
  login?: LoginTransaction
  principal?: AuthPrincipal
  tokens?: TokenSet
}

export function useAuthSession(event: H3Event) {
  const config = useRuntimeConfig(event)
  return useSession<AuthSessionData>(event, {
    name: 'edu_auth',
    password: config.sessionPassword,
    maxAge: 60 * 60 * 24 * 7,
    cookie: {
      httpOnly: true,
      path: '/',
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production'
    }
  })
}

export function sessionExpiresSoon(expiresAt: number, now = Date.now()): boolean {
  return expiresAt <= now + 60_000
}
