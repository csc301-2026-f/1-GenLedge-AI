import type { InventoryView } from './types'

const responseMessage = 'Unexpected snapshot response. Please try again.'
const sourceTypes = ['text', 'number', 'boolean', 'date', 'timestamp', 'json']
const resourceKinds = ['collection', 'table', 'sheet', 'file']
const statuses = ['stable', 'new', 'unknown']
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const optionalText = (value: unknown) => value === undefined || value === null || typeof value === 'string'

function readInventory(data: unknown, snapshotId: string): InventoryView {
  if (!isObject(data) || typeof data.contract_version !== 'string' || data.contract_version.split('.')[0] !== '1') throw new Error(responseMessage)
  const inventory = data.inventory
  if (!isObject(inventory) || inventory.snapshot_id !== snapshotId || !Array.isArray(inventory.resources) || !Array.isArray(inventory.fields)) throw new Error(responseMessage)
  const counts = new Map<string, number>()
  for (const resource of inventory.resources) {
    if (!isObject(resource) || typeof resource.resource_id !== 'string' || typeof resource.name !== 'string' ||
        typeof resource.kind !== 'string' || !resourceKinds.includes(resource.kind) ||
        typeof resource.field_count !== 'number' || !Number.isInteger(resource.field_count) || resource.field_count < 0 || counts.has(resource.resource_id)) throw new Error(responseMessage)
    counts.set(resource.resource_id, 0)
  }
  const refs = new Set<string>()
  for (const field of inventory.fields) {
    if (!isObject(field) || !isObject(field.ref) || typeof field.ref.source_id !== 'string' ||
        typeof field.ref.resource_id !== 'string' || typeof field.ref.field_path !== 'string' ||
        !counts.has(field.ref.resource_id) || typeof field.type !== 'string' || !sourceTypes.includes(field.type) ||
        typeof field.nullable !== 'boolean' || typeof field.repeating !== 'boolean' ||
        !Array.isArray(field.samples) || field.samples.length > 3 || !field.samples.every(sample => typeof sample === 'string') ||
        typeof field.status !== 'string' || !statuses.includes(field.status) ||
        !optionalText(field.ambiguity) || !optionalText(field.native_type)) throw new Error(responseMessage)
    const ref = JSON.stringify([field.ref.resource_id, field.ref.field_path])
    if (refs.has(ref)) throw new Error(responseMessage)
    refs.add(ref)
    counts.set(field.ref.resource_id, counts.get(field.ref.resource_id)! + 1)
  }
  for (const resource of inventory.resources) {
    if (counts.get(resource.resource_id) !== resource.field_count) throw new Error(responseMessage)
  }
  return inventory as InventoryView
}

export async function loadSnapshot(snapshotId: string, signal: AbortSignal): Promise<InventoryView> {
  let response: Response
  try {
    response = await fetch(`/api/sources/snapshots/${encodeURIComponent(snapshotId)}`, {
      credentials: 'include', cache: 'no-store', signal,
    })
  } catch (error) {
    if (error instanceof TypeError) throw new Error('Unable to connect to snapshot storage. Please try again.')
    throw error
  }
  if (response.status === 401) throw new Error('Your session has expired. Sign in again to load snapshots.')
  let data: unknown
  try { data = await response.json() } catch { throw new Error(responseMessage) }
  if (!response.ok) {
    if (isObject(data) && isObject(data.error) && typeof data.error.message === 'string') throw new Error(data.error.message)
    throw new Error('Unable to load the snapshot. Please try again.')
  }
  return readInventory(data, snapshotId)
}
