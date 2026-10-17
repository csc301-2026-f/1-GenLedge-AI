import { forget, stored, store, type Decision } from './client'

// The exact pending request is retained per login/job so retries never invent IDs.
// No model output, source samples or credentials are stored here.
export type SavedEditRequest = {
  edit_id: string
  idempotency_key: string
  target: string
  decision: Decision
  uncertain: boolean
}

const storageKey = (owner: string, jobId: string) => `pending-edit:${JSON.stringify([owner, jobId])}`

export function readPendingEdit(owner: string, jobId: string): SavedEditRequest | null {
  const value = stored(storageKey(owner, jobId))
  if (!value) return null
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const edit = parsed as Record<string, unknown>
    if (typeof edit.edit_id !== 'string' || !edit.edit_id ||
        typeof edit.idempotency_key !== 'string' || !edit.idempotency_key ||
        typeof edit.target !== 'string' || !edit.target ||
        (edit.decision !== 'accept' && edit.decision !== 'reject')) return null
    return { edit_id: edit.edit_id, idempotency_key: edit.idempotency_key, target: edit.target, decision: edit.decision, uncertain: edit.uncertain !== false }
  } catch { return null }
}

export function savePendingEdit(owner: string, jobId: string, edit: SavedEditRequest) {
  store(storageKey(owner, jobId), JSON.stringify(edit))
}

export function clearPendingEdit(owner: string, jobId: string) {
  forget(storageKey(owner, jobId))
}
