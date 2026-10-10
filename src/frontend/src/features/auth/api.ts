export type AuthUser = {
  id: string
  email: string
  role: string
  organizationId: string
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(`/api/auth/${path}`, { ...options, credentials: 'same-origin' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error ?? 'Unable to contact the authentication service.')
  }
  return response
}

async function mutate(path: string, body?: object): Promise<Response> {
  const csrfResponse = await request('csrf')
  const { csrfToken } = await csrfResponse.json()
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    body: JSON.stringify(body ?? {}),
  })
}

export async function login(email: string, password: string, rememberMe: boolean): Promise<AuthUser> {
  const response = await mutate('login', { email, password, rememberMe })
  return (await response.json()).user
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await fetch('/api/auth/me', { credentials: 'same-origin' })
  if (response.status === 401) return null
  if (!response.ok) throw new Error('Unable to restore your session. Please retry.')
  return (await response.json()).user
}

export async function logout(): Promise<void> {
  await mutate('logout')
}
