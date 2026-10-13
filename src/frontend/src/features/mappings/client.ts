// HTTP views of app.agent.contracts and app.common.api_schemas.
export type Decision = 'accept' | 'reject'
export type JobStatus = 'queued' | 'running' | 'revising' | 'awaiting_review' | 'edit_requested' | 'approval_requested' | 'cancelling' | 'blocked' | 'approved' | 'failed' | 'cancelled'
export type Failure = { code: string; message: string; retryable: boolean }
export type Job = { job_id: string; status: JobStatus; source_snapshot_id: string; model_mode: 'fake' | 'live' | null; failure: Failure | null }
export type ReviewPackage = {
  contract_version: string
  model_draft: { revision: number; tables: { id: string; name: string; key: string[]; rationale: string; attributes: { id: string; type: string; confidence: number }[] }[]; unresolved: string[] }
  mapping_draft: { revision: number; mappings: { target: string; sources: string[]; confidence: number; rationale: string | null }[]; unresolved: string[] }
  is_new: Record<string, boolean>
  decisions: Record<string, Decision>
  findings: { code: string; severity: 'blocker' | 'warning' | 'info'; target: string | null; message: string }[]
  coverage: { resource_id: string; field_path: string; disposition: string; reason: string }[]
}
export type PackageResponse = { payload: ReviewPackage | null; status: JobStatus; failure: Failure | null }
export class RoutingError extends Error {
  constructor(message: string, public status: number) { super(message) }
}
async function request<T>(path: string, method = 'GET', body?: unknown, key?: string): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    const result = await fetch(`/api/mappings/jobs${path}`, {
      method, credentials: 'include', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const data = await result.json().catch(() => null)
    if (!result.ok) throw new RoutingError(typeof data?.error?.message === 'string' ? data.error.message : 'Routing request failed. Please retry.', result.status)
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Unexpected routing response.')
    return data as T
  } catch (error) {
    if (error instanceof TypeError || (error instanceof DOMException && error.name === 'AbortError')) {
      throw new Error('Unable to connect to routing. Retry will safely repeat the same request.')
    }
    throw error
  } finally { clearTimeout(timeout) }
}
export const createJob = (snapshot: string | null, key: string) => request<{ job_id: string; status: JobStatus }>('', 'POST', { source_snapshot_id: snapshot }, key)
export const readJob = (id: string) => request<Job>(`/${encodeURIComponent(id)}`)
export async function readPackage(id: string): Promise<PackageResponse> {
  const result = await request<PackageResponse>(`/${encodeURIComponent(id)}/package`)
  if (result.payload && result.payload.contract_version.split('.')[0] !== '1') throw new Error('Unsupported routing package version.')
  return result
}
export const editJob = (id: string, edit_id: string, target: string, decision: Decision) => request<{ payload: ReviewPackage; replayed: boolean }>(`/${encodeURIComponent(id)}/edits`, 'PUT', { edit_id, target, decision })

// Only opaque request/job identifiers are retained in this tab, never packages or credentials.
const fallbackStorage = new Map<string, string>()
export function stored(key: string): string | null {
  try { return sessionStorage.getItem(`routing:${key}`) ?? fallbackStorage.get(key) ?? null } catch { return fallbackStorage.get(key) ?? null }
}
export function store(key: string, value: string) {
  fallbackStorage.set(key, value)
  try { sessionStorage.setItem(`routing:${key}`, value) } catch { /* session storage may be disabled */ }
}
export function forget(key: string) {
  fallbackStorage.delete(key)
  try { sessionStorage.removeItem(`routing:${key}`) } catch { /* session storage may be disabled */ }
}
export function requestKey(scope: string): string {
  const key = stored(scope) || crypto.randomUUID()
  store(scope, key)
  return key
}
