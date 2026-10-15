import { useState } from 'react'
import { T, Btn, Ico, TH, FilterBar, SearchBox, FilterSelect, PageHeader, Alert, TypeTag } from '../../shared'
import type { DiscoveryFieldView, DiscoveryState } from './types'

type Props = {
  sourceName: string
  collectionName: string
  state: DiscoveryState
  onResample?: () => void
  onAdvance?: () => void
  refreshLabel?: string
}

// The caller owns source selection, requests, permissions and snapshot persistence.
export function DiscoverScreen({ sourceName, collectionName, state, onResample, onAdvance, refreshLabel = 'Re-sample' }: Props) {
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const result = state.status === 'ready' ? state.result : undefined
  const changes = state.status === 'ready' ? state.changes : undefined
  const changeStatus = (field: DiscoveryFieldView) => {
    const path = field.path
    if (changes?.added.includes(path)) return 'added'
    if (changes?.typeChanges.some(change => change.path === path)) return 'type-changed'
    return changes ? 'unchanged' : field.status ?? 'observed'
  }
  const fields = result?.fields.filter(field =>
    field.path.toLowerCase().includes(search.toLowerCase()) &&
    (!typeFilter || field.types.some(type => type === typeFilter)) &&
    (!statusFilter || changeStatus(field) === statusFilter)
  ) ?? []

  const fieldTypes = [...new Set(result?.fields.flatMap(field => field.types) ?? [])].sort()
  const fieldStatuses = [...new Set(result?.fields.map(changeStatus) ?? [])].sort()

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, background: T.bg }}>
      <PageHeader title="Schema Discovery" actions={<>
        <Btn onClick={onResample} disabled={!onResample || state.status === 'loading'}><Ico.Refresh />{state.status === 'loading' ? 'Loading…' : refreshLabel}</Btn>
        <Btn variant="primary" onClick={onAdvance} disabled={!onAdvance || !result || result.fields.length === 0}><Ico.Sparkle />{onAdvance ? 'Run AI Routing' : 'Routing not connected'}</Btn>
      </>} />
      <div style={{ padding: '12px 20px', flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ marginBottom: 12, color: T.text }}><strong>{sourceName}</strong> / {collectionName}</div>
        {state.status === 'idle' && <div role="status">Load a saved snapshot to inspect its fields.</div>}
        {state.status === 'loading' && <div role="status">Loading fields…</div>}
        {state.status === 'error' && <div role="alert"><Alert type="error">{state.message}</Alert></div>}
        {result && <>
          <Alert type="info">{result.sampledCount === undefined ? 'Saved inventory metadata. Sampling count and method were not recorded.' : `Sampled ${result.sampledCount} records in source order (up to 500). Fields outside the sample may be missed.`} Nullable describes observed null or missing values.</Alert>
          {result.fields.some(field => field.ambiguity) && <div style={{ marginTop: 12 }}>
            <Alert type="warning">Some sampled dates support both DD/MM/YYYY and MM/DD/YYYY. Confirm the date format before transformation. Values have not been converted.</Alert>
          </div>}
          {changes && <div style={{ marginTop: 12 }} aria-live="polite">
            <Alert type="warning">
              <strong>Sample changes</strong>
              <div>Added: {changes.added.join(', ') || 'None'}</div>
              <div>Missing from this sample: {changes.missing.join(', ') || 'None'}. This does not confirm deletion from the source.</div>
              <div>Type changes: {changes.typeChanges.length === 0 ? 'None' : changes.typeChanges.map(change =>
                `${change.path}: ${change.previousTypes.join(' / ')} → ${change.currentTypes.join(' / ')}`
              ).join('; ')}</div>
            </Alert>
          </div>}
          <div style={{ marginTop: 12, background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflowX: 'auto' }}>
            <FilterBar>
              <label><span className="sr-only">Field path search</span><SearchBox value={search} onChange={setSearch} placeholder="Filter by field path…" /></label>
              <label><span className="sr-only">Observed type filter</span><FilterSelect value={typeFilter} onChange={setTypeFilter} placeholder="All Types" options={fieldTypes.map(type => ({ value: type, label: type }))} /></label>
              <label><span className="sr-only">Change status filter</span><FilterSelect value={statusFilter} onChange={setStatusFilter} placeholder="All Statuses" options={fieldStatuses.map(status => ({ value: status, label: status }))} /></label>
              <span style={{ marginLeft: 'auto', color: T.textMid }}>{fields.length} / {result.fields.length} fields</span>
            </FilterBar>
            <table>
              <thead><tr>
                <TH label="Field Path" col="path" /><TH label="Data Types" col="types" />
                <TH label="Nullable" col="nullable" /><TH label="Repeating" col="repeating" />
                <TH label="Sample Values" col="samples" /><TH label="Status" col="status" />
              </tr></thead>
              <tbody>
                {fields.map(field => <tr key={field.path}>
                  <td style={{ padding: 12, fontFamily: 'monospace', color: T.text }}>
                    {field.path}
                    {field.ambiguity && <div style={{ marginTop: 4, color: 'var(--c-7a4800)', fontSize: 11 }}>Date format ambiguous</div>}
                  </td>
                  <td style={{ padding: 12 }}><div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{field.types.map(type => <TypeTag key={type} type={type} />)}</div>{field.nativeType && <div style={{ marginTop: 4, color: T.textMuted, fontSize: 11 }}>{field.nativeType}</div>}</td>
                  <td style={{ padding: 12, color: T.textMid }}>{field.nullable ? 'Yes' : 'No'}</td>
                  <td style={{ padding: 12, color: T.textMid }}>{field.repeating ? 'Yes' : 'No'}</td>
                  <td style={{ padding: 12 }}><div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{field.samples.length === 0 && <span style={{ color: T.textMuted }}>No samples</span>}{field.samples.map((sample, index) =>
                    <code key={index} style={{ color: T.textMid, overflowWrap: 'anywhere' }}>{sample}</code>
                  )}</div></td>
                  <td style={{ padding: 12, color: T.textMid }}>{changeStatus(field)}</td>
                </tr>)}
              </tbody>
            </table>
            {fields.length === 0 && <div role="status" style={{ padding: 16, color: T.textMid }}>{result.fields.length === 0 ? (result.sampledCount === undefined ? 'No fields in this saved resource.' : 'No fields were observed in this sample.') : 'No fields match these filters.'}</div>}
          </div>
        </>}
      </div>
    </div>
  )
}
