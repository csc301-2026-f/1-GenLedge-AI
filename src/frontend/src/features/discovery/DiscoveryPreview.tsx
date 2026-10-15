import { useState } from 'react'
import { T } from '../../shared'
import { DiscoverScreen } from './DiscoverScreen'
import { previewData } from './previewData'
import { discoveryView } from './view'
import type { DiscoveryState } from './types'

type PreviewMode = 'initial' | 'refreshed' | 'empty' | 'loading' | 'error'

// Temporary host until US2 source reading and discovery HTTP integration are available.
export function DiscoveryPreview({ onAdvance, onInvalidate }: { onAdvance: () => void; onInvalidate: () => void }) {
  const [mode, setMode] = useState<PreviewMode>('initial')
  const states: Record<PreviewMode, DiscoveryState> = {
    initial: { status: 'ready', result: discoveryView(previewData.previous) },
    refreshed: { status: 'ready', result: discoveryView(previewData.current), changes: previewData.changes },
    empty: { status: 'ready', result: discoveryView({ contractVersion: 1, samplingMethod: 'head', sampledCount: 0, fields: [] }) },
    loading: { status: 'loading' },
    error: { status: 'error', message: 'Synthetic error preview: unable to read the selected collection. Use Re-sample to return to the refreshed fixture.' },
  }
  const changeMode = (next: PreviewMode) => { onInvalidate(); setMode(next) }
  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
    <div style={{ padding: '8px 20px', background: T.surface, color: T.textMid, fontSize: 12 }}>
      <label>Synthetic preview (no source connection or persistence): {' '}
        <select value={mode} onChange={event => changeMode(event.target.value as PreviewMode)}>
          <option value="initial">Initial sample</option><option value="refreshed">Refreshed sample</option>
          <option value="empty">Empty sample</option><option value="loading">Loading</option><option value="error">Error</option>
        </select>
      </label>
    </div>
    <DiscoverScreen key={mode} sourceName="Synthetic orders fixture" collectionName="orders" state={states[mode]}
      onResample={() => changeMode('refreshed')} onAdvance={onAdvance} />
  </div>
}
