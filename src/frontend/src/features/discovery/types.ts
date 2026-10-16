// JSON payloads emitted by app.sources.discovery (contract version 1).
export type ObservedType = 'null' | 'boolean' | 'number' | 'string' | 'object' | 'array'
export type DiscoveredField = {
  path: string
  types: ObservedType[]
  nullable: boolean
  repeating: boolean
  samples: (string | number | boolean | null)[]
  ambiguity?: string
}
export type DiscoveryResult = {
  contractVersion: 1
  samplingMethod: 'head'
  sampledCount: number
  fields: DiscoveredField[]
}
export type DiscoveryChanges = {
  contractVersion: 1
  added: string[]
  missing: string[]
  typeChanges: { path: string; previousTypes: ObservedType[]; currentTypes: ObservedType[] }[]
}
export type DiscoveryState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; result: DiscoveryView; changes?: DiscoveryChanges }

export type SourceType = 'text' | 'number' | 'boolean' | 'date' | 'timestamp' | 'json'
export type InventoryField = {
  ref: { source_id: string; resource_id: string; field_path: string }
  type: SourceType
  nullable: boolean
  repeating: boolean
  samples: string[]
  status: 'stable' | 'new' | 'unknown'
  ambiguity?: string | null
  native_type?: string | null
}
export type InventoryView = {
  snapshot_id: string
  resources: { resource_id: string; name: string; kind: 'collection' | 'table' | 'sheet' | 'file'; field_count: number }[]
  fields: InventoryField[]
}
export type DiscoveryFieldView = Omit<DiscoveredField, 'types' | 'samples'> & {
  types: (ObservedType | SourceType)[]
  samples: string[]
  nativeType?: string
  status?: InventoryField['status']
}
export type DiscoveryView = { fields: DiscoveryFieldView[]; sampledCount?: number }
