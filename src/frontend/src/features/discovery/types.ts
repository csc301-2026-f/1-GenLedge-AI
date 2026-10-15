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
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; result: DiscoveryResult; changes?: DiscoveryChanges }
