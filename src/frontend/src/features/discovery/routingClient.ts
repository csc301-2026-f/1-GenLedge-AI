// Discovery's consumer of the shared CreateMappingJobRequest/Response contract.
const jobStatuses = ['queued', 'running', 'revising', 'awaiting_review', 'edit_requested', 'approval_requested', 'cancelling', 'blocked', 'approved', 'failed', 'cancelled'] as const
export type RoutingReceipt = { job_id: string; status: typeof jobStatuses[number] }
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const responseMessage = 'Unexpected routing response. Retry will repeat the same request.'

async function readResponse(response: Response, expectedStatus: number): Promise<unknown> {
  if (response.status === 401) throw new Error('Your session has expired. Sign in again before submitting to routing.')
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = isObject(data) ? data.error : undefined
    if (isObject(error) && typeof error.message === 'string') throw new Error(error.message)
    if (typeof error === 'string') throw new Error(error)
    if (response.status === 404) throw new Error('The routing API is not available in this application yet.')
    if (response.status === 503) throw new Error('Routing is not configured or is temporarily unavailable.')
    throw new Error('Unable to submit to routing. Retry will repeat the same request.')
  }
  if (response.status !== expectedStatus) throw new Error(responseMessage)
  return data
}

export async function submitSnapshot(snapshotId: string, key: string, signal: AbortSignal): Promise<RoutingReceipt> {
  try {
    const csrf = await readResponse(await fetch('/api/auth/csrf', {
      credentials: 'include', cache: 'no-store', signal,
    }), 200)
    if (!isObject(csrf) || typeof csrf.csrfToken !== 'string') throw new Error('Unexpected authentication response. Please sign in again.')
    const data = await readResponse(await fetch('/api/mappings/jobs', {
      method: 'POST', credentials: 'include', cache: 'no-store', signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrfToken, 'Idempotency-Key': key },
      body: JSON.stringify({ source_snapshot_id: snapshotId }),
    }), 202)
    if (!isObject(data) || typeof data.job_id !== 'string' || !data.job_id.trim() ||
        typeof data.status !== 'string' || !jobStatuses.some(status => status === data.status)) throw new Error(responseMessage)
    return data as RoutingReceipt
  } catch (error) {
    if (error instanceof TypeError) throw new Error('Unable to connect to routing. Retry will repeat the same request.')
    throw error
  }
}
