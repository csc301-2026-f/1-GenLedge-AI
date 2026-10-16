import { useEffect, useRef, useState } from 'react'
import { submitSnapshot, type RoutingReceipt } from './routingClient'

type HandoffState = { status: 'idle' } | { status: 'submitting' } | { status: 'error'; message: string } | { status: 'accepted'; receipt: RoutingReceipt }
type Attempt = { key: string; state: HandoffState }

export function useRoutingHandoff(snapshotId: string | undefined) {
  // Keep retry identity across resource changes and reloads within this container.
  const [attempts, setAttempts] = useState(() => new Map<string, Attempt>())
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => { request.current?.abort(); request.current = null }, [])
  const state: HandoffState = snapshotId ? attempts.get(snapshotId)?.state ?? { status: 'idle' } : { status: 'idle' }

  const submit = async () => {
    if (!snapshotId || request.current) return
    const attempt = attempts.get(snapshotId)
    if (attempt?.state.status === 'accepted') return
    const key = attempt?.key ?? crypto.randomUUID()
    const update = (next: HandoffState) => setAttempts(previous => new Map(previous).set(snapshotId, { key, state: next }))
    const controller = new AbortController()
    request.current = controller
    const timeout = setTimeout(() => controller.abort(), 15000)
    update({ status: 'submitting' })
    try {
      const receipt = await submitSnapshot(snapshotId, key, controller.signal)
      if (request.current !== controller) return
      update({ status: 'accepted', receipt })
    } catch (error) {
      if (request.current !== controller) return
      update({ status: 'error', message: controller.signal.aborted
        ? 'Routing request timed out. It may have reached the server. Retry will repeat the same request.'
        : error instanceof Error ? error.message : 'Unable to submit to routing.' })
    } finally {
      clearTimeout(timeout)
      if (request.current === controller) request.current = null
    }
  }
  return { state, submit }
}
