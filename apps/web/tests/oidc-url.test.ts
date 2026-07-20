import { describe, expect, it } from 'vitest'

import { buildAuthorizationUrl } from '../server/utils/oidc'

describe('OIDC authorization request', () => {
  it('uses authorization code, PKCE, state, and nonce', () => {
    const url = new URL(buildAuthorizationUrl(
      'https://issuer.example.test/authorize',
      {
        clientId: 'web-client',
        codeChallenge: 'challenge',
        nonce: 'nonce',
        redirectUri: 'https://web.example.test/api/auth/callback',
        state: 'state'
      }
    ))

    expect(Object.fromEntries(url.searchParams)).toEqual({
      client_id: 'web-client',
      code_challenge: 'challenge',
      code_challenge_method: 'S256',
      nonce: 'nonce',
      redirect_uri: 'https://web.example.test/api/auth/callback',
      response_type: 'code',
      scope: 'openid offline_access',
      state: 'state'
    })
  })
})
