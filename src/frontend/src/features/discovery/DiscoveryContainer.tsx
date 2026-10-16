import { useEffect, useRef, useState } from 'react'
import { Alert, Btn, T } from '../../shared'
import { DiscoverScreen } from './DiscoverScreen'
import { loadSnapshot } from './client'
import { snapshotView } from './view'
import { useRoutingHandoff } from './useRoutingHandoff'
import type { DiscoveryState, InventoryView } from './types'

type LoadState = { status: 'idle' } | { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; inventory: InventoryView }

export function DiscoveryContainer({ onInvalidate }: { onInvalidate: () => void }) {
  const [snapshotId, setSnapshotId] = useState('')
  const [resourceId, setResourceId] = useState('')
  const [loaded, setLoaded] = useState<LoadState>({ status: 'idle' })
  const inventory = loaded.status === 'ready' ? loaded.inventory : undefined
  const handoff = useRoutingHandoff(inventory?.snapshot_id)
  const submitting = handoff.state.status === 'submitting'
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => { request.current?.abort(); request.current = null }, [])

  const load = async (id: string) => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    const timeout = setTimeout(() => controller.abort(), 15000)
    setLoaded({ status: 'loading' }); onInvalidate()
    try {
      const inventory = await loadSnapshot(id, controller.signal)
      if (controller.signal.aborted) return
      setResourceId(inventory.resources[0]?.resource_id ?? '')
      setLoaded({ status: 'ready', inventory })
    } catch (error) {
      if (request.current !== controller) return
      setLoaded({ status: 'error', message: controller.signal.aborted ? 'Snapshot request timed out. Please try again.' : error instanceof Error ? error.message : 'Unable to load the snapshot.' })
    } finally { clearTimeout(timeout) }
  }
  const state: DiscoveryState = loaded.status === 'ready' ? { status: 'ready', result: snapshotView(loaded.inventory, resourceId) } : loaded

  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
    <form onSubmit={event => { event.preventDefault(); const id = snapshotId.trim(); if (id && loaded.status !== 'loading' && !submitting) void load(id) }} style={{ padding: '12px 20px', background: T.surface, color: T.text, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
      <label>Snapshot ID {' '}<input disabled={submitting} value={snapshotId} onChange={event => {
        request.current?.abort(); request.current = null
        setSnapshotId(event.target.value); setLoaded({ status: 'idle' }); onInvalidate()
      }} /></label>
      <Btn type="submit" disabled={!snapshotId.trim() || loaded.status === 'loading' || submitting}>Load snapshot</Btn>
      {inventory && <label>Resource {' '}<select value={resourceId} disabled={inventory.resources.length === 0} onChange={event => setResourceId(event.target.value)}>
        {inventory.resources.length === 0 && <option value="">No resources</option>}
        {inventory.resources.map(resource => <option key={resource.resource_id} value={resource.resource_id}>{resource.name}</option>)}
      </select></label>}
    </form>
    {inventory && <div style={{ padding: '8px 20px', color: T.text }}>
      <p>Routing uses the entire saved snapshot, including all resources. Field filters only affect this view.</p>
      {handoff.state.status === 'submitting' && <div role="status">Submitting snapshot {inventory.snapshot_id}…</div>}
      {handoff.state.status === 'error' && <div role="alert"><Alert type="error">{handoff.state.message}</Alert></div>}
      {handoff.state.status === 'accepted' && <div role="status"><Alert type="info">
        Job receipt for snapshot {inventory.snapshot_id}: {handoff.state.receipt.job_id}. Status reported by API: {handoff.state.receipt.status}. Routing results are not loaded here.
      </Alert></div>}
    </div>}
    <DiscoverScreen key={JSON.stringify([inventory?.snapshot_id, resourceId])} sourceName={inventory ? `Snapshot ${inventory.snapshot_id}` : 'Saved snapshot'}
      collectionName={inventory?.resources.find(resource => resource.resource_id === resourceId)?.name ?? ''}
      state={state} refreshLabel="Reload snapshot" onResample={inventory && !submitting ? () => void load(inventory.snapshot_id) : undefined}
      onAdvance={inventory && inventory.fields.length > 0 ? () => void handoff.submit() : undefined}
      advanceDisabled={submitting || handoff.state.status === 'accepted'}
      advanceLabel={submitting ? 'Submitting…' : handoff.state.status === 'accepted' ? 'Request submitted' : handoff.state.status === 'error' ? 'Retry routing request' : 'Submit snapshot to routing'} />
  </div>
}
