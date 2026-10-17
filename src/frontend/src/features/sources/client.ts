export const MAX_FILE_BYTES = 25_000_000
export const ACCEPTED_FILES = '.csv,.tsv,.xlsx,.xls,.json,.ndjson'

export type ValidationResult = {
  status: 'validated'
  persisted: false
  filename: string
  format: string
  sizeBytes: number
  collections: { name: string; key: string; rowCount: number; warnings: string[] }[]
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isResult(value: unknown): value is ValidationResult {
  return isObject(value) && value.status === 'validated' && value.persisted === false &&
    typeof value.filename === 'string' && typeof value.format === 'string' &&
    typeof value.sizeBytes === 'number' && Array.isArray(value.collections) && value.collections.length > 0 &&
    value.collections.every(c => isObject(c) && typeof c.name === 'string' && typeof c.key === 'string' &&
      typeof c.rowCount === 'number' && Number.isInteger(c.rowCount) && c.rowCount >= 0 &&
      Array.isArray(c.warnings) && c.warnings.every(w => typeof w === 'string'))
}

async function csrfToken(signal: AbortSignal): Promise<string> {
  const response = await fetch('/api/sources/uploads/csrf', { credentials: 'include', signal })
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(isObject(data) && typeof data.error === 'string'
      ? data.error : 'Unable to prepare file validation. Please try again.')
  }
  if (!isObject(data) || typeof data.csrfToken !== 'string') {
    throw new Error('Unexpected validation response. Please try again.')
  }
  return data.csrfToken
}

export async function validateFile(file: File, signal: AbortSignal): Promise<ValidationResult> {
  const body = new FormData()
  body.append('file', file)
  try {
    const token = await csrfToken(signal)
    const response = await fetch('/api/sources/uploads/validate', {
      method: 'POST', credentials: 'include', signal,
      headers: { 'X-CSRF-Token': token }, body,
    })
    const data: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(isObject(data) && typeof data.error === 'string'
        ? data.error : 'Unable to validate the file. Please try again.')
    }
    if (!isResult(data)) throw new Error('Unexpected validation response. Please try again.')
    return data
  } catch (error) {
    if (error instanceof TypeError) throw new Error('Unable to connect to the validation service. Please try again.')
    throw error
  }
}


export type SavedSource = {
  sourceId: string; batchId: string; filename: string; environment: string
  format: string; sizeBytes: number; uploadedAt: string
  collections: { collectionId: string; name: string; rowCount: number; warnings: string[] }[]
}
function isSource(v: unknown): v is SavedSource {
  return isObject(v) && typeof v.sourceId === 'string' && typeof v.batchId === 'string' &&
    typeof v.filename === 'string' && typeof v.environment === 'string' && typeof v.format === 'string' &&
    typeof v.sizeBytes === 'number' && typeof v.uploadedAt === 'string' && Array.isArray(v.collections) &&
    v.collections.every(c => isObject(c) && typeof c.collectionId === 'string' && typeof c.name === 'string' &&
      typeof c.rowCount === 'number' && Number.isInteger(c.rowCount) && c.rowCount >= 0 &&
      Array.isArray(c.warnings) && c.warnings.every(w => typeof w === 'string'))
}
const uncertain = 'Import completion could not be confirmed. Refresh the source list before retrying.'
export async function importFile(file: File, signal: AbortSignal): Promise<SavedSource> {
  const body = new FormData()
  body.append('file', file)
  const token = await csrfToken(signal)
  let response: Response
  try {
    response = await fetch('/api/sources/uploads', { method: 'POST', credentials: 'include', signal,
      headers: { 'X-CSRF-Token': token }, body })
  } catch { throw new Error(uncertain) }
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(isObject(data) && typeof data.error === 'string' ? data.error : uncertain)
  if (!isObject(data) || data.persisted !== true || data.status !== 'imported' || !isSource(data.source)) throw new Error(uncertain)
  return data.source
}
export async function listSources(signal: AbortSignal): Promise<SavedSource[]> {
  const response = await fetch('/api/sources', { credentials: 'include', signal })
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(isObject(data) && typeof data.error === 'string' ? data.error : 'Unable to load saved sources.')
  if (!isObject(data) || !Array.isArray(data.sources) || !data.sources.every(isSource)) throw new Error('Unexpected source list response.')
  return data.sources
}
