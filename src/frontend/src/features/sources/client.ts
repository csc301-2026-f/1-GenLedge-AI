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
