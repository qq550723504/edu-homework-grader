export default defineNitroPlugin(() => {
  const config = useRuntimeConfig()
  if (config.appEnv !== 'production') return
  if (config.sessionPassword === 'development-only-session-password-change-me') {
    throw new Error('NUXT_SESSION_PASSWORD must be configured in production')
  }
  const issuerUrl = new URL(config.oidcIssuer)
  if (issuerUrl.protocol !== 'https:' || issuerUrl.hostname === 'localhost') {
    throw new Error('a non-local HTTPS OIDC issuer is required in production')
  }
})
