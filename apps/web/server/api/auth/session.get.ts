import { currentPrincipal } from '../../utils/core-api'
import { useAuthSession } from '../../utils/auth-session'

export default defineEventHandler(async (event) => {
  try {
    const principal = await currentPrincipal(event)
    const session = await useAuthSession(event)
    return { ...principal, csrf_token: session.data.csrfToken }
  } catch (error: any) {
    if (error?.statusCode === 401) return null
    throw error
  }
})
