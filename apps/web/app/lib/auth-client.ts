import { resetDraftDatabase } from './drafts'

type LogoutRequest = <T>(url: string, options?: {
  method?: 'POST'
  headers?: Record<string, string>
}) => Promise<T>

export async function logout(
  request: LogoutRequest,
  clearDrafts: () => Promise<void> = resetDraftDatabase
): Promise<void> {
  const session = await request<{ csrf_token: string }>('/api/auth/session')
  await request('/api/auth/logout', {
    method: 'POST',
    headers: { 'X-CSRF-Token': session.csrf_token }
  })
  await clearDrafts()
}
