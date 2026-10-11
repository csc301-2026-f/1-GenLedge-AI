export type AuthUser = {
  id: 'demo-user'
  username: string
  email: string
  role: 'Administrator'
}

const signedOut = Symbol('signed-out')
const connectionMessage = 'Unable to connect to the authentication service. Please try again.'
const responseMessage = 'Unexpected authentication response. Please try again.'

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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    })
    if (path === 'me' && response.status === 401) return signedOut
    const data: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      const error = isObject(data) && isObject(data.error) ? data.error : null
      if (error && (error.code === 'invalid_request' || error.code === 'unauthorized') && typeof error.message === 'string') {
        throw new Error(error.message)
      }
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

function readUser(data: unknown): AuthUser {
  const user = isObject(data) ? data.user : null
  if (!isObject(user) || user.id !== 'demo-user' || user.role !== 'Administrator' ||
      typeof user.username !== 'string' || !user.username.trim() || user.email !== user.username) {
    throw new Error(responseMessage)
  }
  return { id: user.id, username: user.username, email: user.username, role: user.role }
}

export async function login(username: string, password: string, remember_me: boolean): Promise<AuthUser> {
  return readUser(await request('login', 'POST', { username, password, remember_me }))
}

export async function currentUser(): Promise<AuthUser | null> {
  const data = await request('me')
  // Only HTTP 401 is signed out; even a successful JSON null is invalid.
  return data === signedOut ? null : readUser(data)
}

export async function logout(): Promise<void> {
  const data = await request('logout', 'POST')
  if (!isObject(data) || data.success !== true) throw new Error(responseMessage)
}
