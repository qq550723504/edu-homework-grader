import { useAuthSession } from '../../utils/auth-session'
import { requireCsrfToken } from '../../utils/csrf'

export default defineEventHandler(async (event) => {
  await requireCsrfToken(event)
  const session = await useAuthSession(event)
  await session.clear()
  return { ok: true }
})
