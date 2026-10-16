import type { DiscoveryResult, DiscoveryView, InventoryView } from './types'

export function discoveryView(result: DiscoveryResult): DiscoveryView {
  return { sampledCount: result.sampledCount, fields: result.fields.map(field => ({
    ...field, samples: field.samples.map(sample => JSON.stringify(sample)),
  })) }
}

export function snapshotView(inventory: InventoryView, resourceId: string): DiscoveryView {
  return { fields: inventory.fields.filter(field => field.ref.resource_id === resourceId).map(field => ({
    path: field.ref.field_path, types: [field.type], samples: field.samples,
    nullable: field.nullable, repeating: field.repeating, status: field.status,
    ambiguity: field.ambiguity ?? undefined, nativeType: field.native_type ?? undefined,
  })) }
}
