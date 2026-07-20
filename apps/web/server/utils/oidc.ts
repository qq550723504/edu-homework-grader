import * as oauth from 'oauth4webapi'

export interface AuthorizationRequestInput {
  clientId: string
  codeChallenge: string
  nonce: string
  redirectUri: string
  state: string
}

export function buildAuthorizationUrl(
  authorizationEndpoint: string,
  input: AuthorizationRequestInput
): string {
  const url = new URL(authorizationEndpoint)
  url.searchParams.set('client_id', input.clientId)
  url.searchParams.set('redirect_uri', input.redirectUri)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('scope', 'openid offline_access')
  url.searchParams.set('code_challenge', input.codeChallenge)
  url.searchParams.set('code_challenge_method', 'S256')
  url.searchParams.set('state', input.state)
  url.searchParams.set('nonce', input.nonce)
  return url.toString()
}

export async function discoverOpenIdConfiguration(
  issuer: string,
  allowInsecure = false
): Promise<oauth.AuthorizationServer> {
  const issuerUrl = new URL(issuer)
  const response = await oauth.discoveryRequest(issuerUrl, {
    algorithm: 'oidc',
    [oauth.allowInsecureRequests]: allowInsecure
  })
  return oauth.processDiscoveryResponse(issuerUrl, response)
}

export async function exchangeAuthorizationCode(input: {
  authorizationServer: oauth.AuthorizationServer
  clientId: string
  callbackUrl: URL
  codeVerifier: string
  expectedNonce: string
  expectedState: string
  redirectUri: string
  allowInsecure?: boolean
}): Promise<oauth.TokenEndpointResponse> {
  const client = { client_id: input.clientId }
  const parameters = oauth.validateAuthResponse(
    input.authorizationServer,
    client,
    input.callbackUrl,
    input.expectedState
  )
  const response = await oauth.authorizationCodeGrantRequest(
    input.authorizationServer,
    client,
    oauth.None(),
    parameters,
    input.redirectUri,
    input.codeVerifier,
    { [oauth.allowInsecureRequests]: input.allowInsecure }
  )
  return oauth.processAuthorizationCodeResponse(input.authorizationServer, client, response, {
    expectedNonce: input.expectedNonce,
    requireIdToken: true
  })
}

export async function refreshAccessToken(input: {
  authorizationServer: oauth.AuthorizationServer
  clientId: string
  refreshToken: string
  allowInsecure?: boolean
}): Promise<oauth.TokenEndpointResponse> {
  const client = { client_id: input.clientId }
  const response = await oauth.refreshTokenGrantRequest(
    input.authorizationServer,
    client,
    oauth.None(),
    input.refreshToken,
    { [oauth.allowInsecureRequests]: input.allowInsecure }
  )
  return oauth.processRefreshTokenResponse(input.authorizationServer, client, response)
}
