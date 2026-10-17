import { useState, useMemo, useEffect } from 'react'
import { T, StatusPill, Btn, Ico, Pager, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Alert } from '../../shared'
import type { SortDir } from '../../shared'
import { listSources } from './client'
import type { SavedSource } from './client'
import { UploadFileModal } from './UploadFileModal'

// ─── US2 — Data Sources ───────────────────────────────────────────────────────
export function SourcesScreen() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [page, setPage] = useState(1)
  const [sortCol, setSortCol] = useState('lastIngested')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [showUpload, setShowUpload] = useState(false)
  const [sources, setSources] = useState<SavedSource[]>([])
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setLoadError('')
    listSources(controller.signal).then(data => {
      if (!controller.signal.aborted) setSources(data)
    }).catch(error => {
      if (!controller.signal.aborted) {
        setSources([])
        setLoadError(error instanceof Error ? error.message : 'Unable to load saved sources.')
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [revision])

  const handleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const filtered = useMemo(() => {
    let d = sources.map(source => ({ id: source.sourceId, name: source.filename,
      type: source.format.toUpperCase(), owner: source.environment,
      documents: source.collections.reduce((sum, c) => sum + c.rowCount, 0),
      collections: source.collections.length, status: 'ready', lastIngested: source.uploadedAt }))
    if (search) d = d.filter(r => r.name.toLowerCase().includes(search.toLowerCase()) || r.owner.toLowerCase().includes(search.toLowerCase()) || r.id.toLowerCase().includes(search.toLowerCase()))
    if (statusFilter) d = d.filter(r => r.status === statusFilter)
    if (typeFilter) d = d.filter(r => r.type === typeFilter)
    d.sort((a, b) => {
      const v = sortDir === 'asc' ? 1 : -1
      if (sortCol === 'documents') return (a.documents - b.documents) * v
      const aVal = a[sortCol as keyof typeof a] ?? ''
      const bVal = b[sortCol as keyof typeof b] ?? ''
      return aVal < bVal ? -v : aVal > bVal ? v : 0
    })
    return d
  }, [sources, search, statusFilter, typeFilter, sortCol, sortDir])

  const pageSize = 10
  const paged = filtered.slice((page - 1) * pageSize, page * pageSize)

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg }}>
      <PageHeader
        title="Data Sources"
        subtitle="Manage ingestion sources: uploaded files and connected databases"
        actions={
          <>
            <Btn variant="secondary" disabled><Ico.Database /> Connect Database</Btn>
            <Btn variant="primary" onClick={() => setShowUpload(true)}><Ico.Upload /> Upload File</Btn>
          </>
        }
      />

      <div style={{ padding: '8px 20px' }}>
        <Btn variant="secondary" disabled={loading} onClick={() => setRevision(n => n + 1)}>Refresh Sources</Btn>
        <span style={{ marginLeft: 12 }}>Database connections and discovery are not available yet.</span>
        {loading && <p role="status">Loading saved sources…</p>}
        {loadError && <div role="alert"><Alert type="error">{loadError}</Alert></div>}
      </div>
      {/* Summary row */}
      <div style={{ display: 'flex', gap: 1, padding: '12px 20px', background: T.bg, flexShrink: 0 }}>
        {[
          { label: 'Total Sources', value: sources.length.toLocaleString() },
          { label: 'Ready', value: sources.length.toLocaleString() },
          { label: 'Total Documents', value: sources.reduce((sum, s) => sum + s.collections.reduce((n, c) => n + c.rowCount, 0), 0).toLocaleString() },
          { label: 'Collections', value: sources.reduce((sum, s) => sum + s.collections.length, 0).toLocaleString() },
          { label: 'Last Activity', value: sources[0] ? new Date(sources[0].uploadedAt).toLocaleString() : '—' },
        ].map(s => (
          <div key={s.label} style={{ flex: 1, background: T.surface, border: `1px solid ${T.border}`, padding: '10px 14px', marginRight: 8, borderRadius: 3 }}>
            <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: `calc(${18}px * var(--font-scale, 1))`, fontWeight: 700, color: T.text }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Table panel */}
      <div style={{ flex: 1, padding: '0 20px 20px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
          <FilterBar>
            <SearchBox value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder="Search by name, environment, source ID…" width={290} />
            <FilterSelect value={statusFilter} onChange={v => { setStatusFilter(v); setPage(1) }} placeholder="All Statuses"
              options={[{ value: 'ready', label: 'Ready' }]} />
            <FilterSelect value={typeFilter} onChange={v => { setTypeFilter(v); setPage(1) }} placeholder="All Types"
              options={[{ value: 'XLSX', label: 'XLSX' }, { value: 'CSV', label: 'CSV' }, { value: 'TSV', label: 'TSV' }, { value: 'XLS', label: 'XLS' }, { value: 'JSON', label: 'JSON' }, { value: 'NDJSON', label: 'NDJSON' }]} />
            {(search || statusFilter || typeFilter) && (
              <Btn variant="ghost" onClick={() => { setSearch(''); setStatusFilter(''); setTypeFilter('') }}>Clear filters</Btn>
            )}
            <span style={{ marginLeft: 'auto', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>{filtered.length} result{filtered.length !== 1 ? 's' : ''}</span>
          </FilterBar>

          <div style={{ overflow: 'auto', flex: 1 }}>
            <table style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <TH label="Source ID" col="id" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={100} />
                  <TH label="Source Name" col="name" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                  <TH label="Type" col="type" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={80} />
                  <TH label="Environment" col="owner" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={140} />
                  <TH label="Collections" col="collections" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={100} align="right" />
                  <TH label="Documents" col="documents" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={110} align="right" />
                  <TH label="Status" col="status" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={110} />
                  <TH label="Last Ingested" col="lastIngested" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={150} />
                  <th style={{ width: 120, minWidth: 120, position: 'sticky', right: 0, zIndex: 3, background: T.tableHead, borderBottom: `1px solid ${T.border}`, boxShadow: '-1px 0 0 0 var(--c-dfe1e6)' }} />
                </tr>
              </thead>
              <tbody>
                {paged.map(row => (
                  <TR key={row.id}
                    actions={<div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 4 }}>
                      <Btn variant="ghost" disabled><Ico.Search /> Discover</Btn>
                    </div>}>
                    <TD mono muted tooltip={row.id}>{row.id}</TD>
                    <TD tooltip={row.name}><span style={{ color: 'var(--link-color)', fontWeight: 500 }}>{row.name}</span></TD>
                    <TD tooltip={row.type}><span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 600, background: T.tableHead, border: `1px solid ${T.border}`, borderRadius: 2, padding: '1px 6px', color: T.textMid }}>{row.type}</span></TD>
                    <TD muted tooltip={row.owner}>{row.owner}</TD>
                    <TD mono right tooltip={String(row.collections)}>{row.collections}</TD>
                    <TD mono right tooltip={row.documents.toLocaleString()}>{row.documents.toLocaleString()}</TD>
                    <TD tooltip={row.status}><StatusPill status={row.status} /></TD>
                    <TD mono muted nowrap tooltip={row.lastIngested}>{row.lastIngested}</TD>
                  </TR>
                ))}
                {paged.length === 0 && (
                  <tr><td colSpan={9} style={{ padding: '32px 16px', textAlign: 'center', color: T.textMid, fontSize: `calc(${13}px * var(--font-scale, 1))`}}>{loading ? 'Loading…' : loadError ? 'Source list unavailable.' : sources.length ? 'No records match the current filters.' : 'No saved sources yet. Upload a file to get started.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <Pager total={filtered.length} page={page} pageSize={pageSize} onPage={setPage} />
        </div>
      </div>

      {showUpload && (
        <UploadFileModal onClose={() => setShowUpload(false)} onImported={() => { setPage(1); setRevision(n => n + 1) }} />
      )}
    </div>
  )
}
