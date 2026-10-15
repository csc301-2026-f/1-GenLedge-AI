export type AuthUser = {
  id: string
  email: string
  role: string
  organizationId: string
}

const connectionMessage = 'Unable to connect to the authentication service. Please try again.'
const responseMessage = 'Unexpected authentication response. Please try again.'
const signedOut = Symbol('signed-out')

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function request(path: string, method = 'GET', body?: unknown): Promise<unknown> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(`/api/auth/${path}`, {
      method,
      credentials: 'include',
      signal: controller.signal,
      ...(body === undefined ? {} : {
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': await csrfToken() },
        body: JSON.stringify(body),
      }),
    })
    if (path === 'me' && response.status === 401) return signedOut
    const data: unknown = response.status === 204 ? null : await response.json().catch(() => null)
    if (!response.ok) {
      const error = isObject(data) ? data.error : null
      if (typeof error === 'string') throw new Error(error)
      throw new Error(responseMessage)
    }
    return data
  } catch (error) {
    if (error instanceof TypeError || (error instanceof DOMException && error.name === 'AbortError')) {
      throw new Error(connectionMessage)
    }
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

async function csrfToken(): Promise<string> {
  const data = await request('csrf')
  if (!isObject(data) || typeof data.csrfToken !== 'string') throw new Error(responseMessage)
  return data.csrfToken
}

function readUser(data: unknown): AuthUser {
  const user = isObject(data) ? data.user : null
  if (!isObject(user) || typeof user.id !== 'string' || typeof user.email !== 'string' ||
      typeof user.role !== 'string' || typeof user.organizationId !== 'string') {
    throw new Error(responseMessage)
  }
  return { id: user.id, email: user.email, role: user.role, organizationId: user.organizationId }
}

export async function login(email: string, password: string, rememberMe: boolean): Promise<AuthUser> {
  return readUser(await request('login', 'POST', { email, password, rememberMe }))
}

export async function currentUser(): Promise<AuthUser | null> {
  const data = await request('me')
  return data === signedOut ? null : readUser(data)
}

export async function logout(): Promise<void> {
  await request('logout', 'POST', {})
}
