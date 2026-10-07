import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert, TypeTag } from '../../shared'
import type { Screen, Nav } from '../../app/types'
import { SOURCES_DATA } from '../sources/data'

// ─── US3 — Schema Discovery ───────────────────────────────────────────────────
type CollectionName = 'orders' | 'order_lines' | 'customers'

const FIELD_DATA: Record<CollectionName, { path: string; type: string; nullable: boolean; repeating: boolean; samples: string[]; status: string; ambiguous?: boolean }[]> = {
  orders: [
    { path: '_id', type: 'ObjectId', nullable: false, repeating: false, samples: ['64a1f09b...', '64a2c341...'], status: 'stable' },
    { path: 'order_no', type: 'string', nullable: false, repeating: false, samples: ['ORD-10042', 'ORD-10043'], status: 'stable' },
    { path: 'customer_id', type: 'ObjectId', nullable: false, repeating: false, samples: ['63f2a1...', '641cc4...'], status: 'stable' },
    { path: 'customer_name', type: 'string', nullable: false, repeating: false, samples: ['Apex Corp', 'RiverView LLC'], status: 'stable' },
    { path: 'total', type: 'number', nullable: false, repeating: false, samples: ['2840.50', '990.00', '4120.75'], status: 'stable' },
    { path: 'order_date', type: 'string', nullable: false, repeating: false, samples: ['03/04/2026', '04/05/2026'], status: 'stable', ambiguous: true },
    { path: 'status', type: 'string', nullable: false, repeating: false, samples: ['fulfilled', 'pending'], status: 'stable' },
    { path: 'lines', type: 'array', nullable: false, repeating: true, samples: ['[2 items]', '[4 items]'], status: 'stable' },
    { path: 'lines[].sku', type: 'string', nullable: false, repeating: true, samples: ['SKU-001', 'SKU-884'], status: 'stable' },
    { path: 'lines[].qty', type: 'number', nullable: false, repeating: true, samples: ['2', '10', '1'], status: 'stable' },
    { path: 'lines[].unit_price', type: 'number', nullable: false, repeating: true, samples: ['142.00', '99.00'], status: 'stable' },
    { path: 'lines[].discount_pct', type: 'number', nullable: true, repeating: true, samples: ['0', '0.1', '0.05'], status: 'new' },
    { path: 'shipping_address.city', type: 'string', nullable: true, repeating: false, samples: ['Austin', 'Denver'], status: 'stable' },
    { path: 'shipping_address.zip', type: 'string', nullable: true, repeating: false, samples: ['78701', '80202'], status: 'stable' },
    { path: 'tags', type: 'array', nullable: true, repeating: true, samples: ['["rush","b2b"]', '["standard"]'], status: 'stable' },
  ],
  order_lines: [
    { path: '_id', type: 'ObjectId', nullable: false, repeating: false, samples: ['...'], status: 'stable' },
    { path: 'order_id', type: 'ObjectId', nullable: false, repeating: false, samples: ['...'], status: 'stable' },
    { path: 'sku', type: 'string', nullable: false, repeating: false, samples: ['SKU-001', 'SKU-884'], status: 'stable' },
    { path: 'qty', type: 'number', nullable: false, repeating: false, samples: ['2', '10', '1'], status: 'stable' },
    { path: 'unit_price', type: 'number', nullable: false, repeating: false, samples: ['142.00', '99.00'], status: 'stable' },
  ],
  customers: [
    { path: '_id', type: 'ObjectId', nullable: false, repeating: false, samples: ['...'], status: 'stable' },
    { path: 'name', type: 'string', nullable: false, repeating: false, samples: ['Apex Corp', 'RiverView LLC'], status: 'stable' },
    { path: 'email', type: 'string', nullable: false, repeating: false, samples: ['ap@apex.com', 'rv@river.com'], status: 'stable' },
    { path: 'industry', type: 'string', nullable: true, repeating: false, samples: ['Manufacturing', 'Finance'], status: 'stable' },
    { path: 'tier', type: 'string', nullable: true, repeating: false, samples: ['gold', 'silver'], status: 'new' },
    { path: 'created_at', type: 'date', nullable: false, repeating: false, samples: ['2024-01-15', '2024-03-02'], status: 'stable' },
  ],
}

export function DiscoverScreen({ onNav, onAdvance, onInvalidate }: { onNav: Nav; onAdvance: () => void; onInvalidate: () => void }) {
  const [selectedSrcId, setSelectedSrcId] = useState('SRC-0041')
  const [srcSearch, setSrcSearch] = useState('')
  const [srcDropOpen, setSrcDropOpen] = useState(false)
  const [tab, setTab] = useState<CollectionName>('orders')
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [resampling, setResampling] = useState(false)
  const srcDropRef = useRef<HTMLDivElement>(null)

  const selectedSrc = SOURCES_DATA.find(s => s.id === selectedSrcId) ?? SOURCES_DATA[0]

  const filteredSources = useMemo(() => {
    const q = srcSearch.toLowerCase()
    return SOURCES_DATA.filter(s =>
      !q || s.id.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
    )
  }, [srcSearch])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (srcDropRef.current && !srcDropRef.current.contains(e.target as Node)) setSrcDropOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const fields = useMemo(() => {
    let d = FIELD_DATA[tab]
    if (search) d = d.filter(f => f.path.includes(search))
    if (typeFilter) d = d.filter(f => f.type === typeFilter)
    if (statusFilter) d = d.filter(f => f.status === statusFilter)
    return d
  }, [tab, search, typeFilter, statusFilter])

  const resample = () => { setResampling(true); setTimeout(() => setResampling(false), 1600) }

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg }}>
      <PageHeader
        title="Schema Discovery"
        actions={
          <>
            <Btn variant="secondary" onClick={() => { onInvalidate(); resample() }} disabled={resampling}><Ico.Refresh />{resampling ? 'Resampling…' : 'Re-sample'}</Btn>
            <Btn variant="primary" onClick={onAdvance}><Ico.Sparkle /> Run AI Routing</Btn>
          </>
        }
      />

      {/* Source selector */}
      <div style={{ padding: '12px 20px 0', flexShrink: 0 }}>
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 600, color: T.textMid, whiteSpace: 'nowrap' }}>Data Source</span>
          <div ref={srcDropRef} style={{ position: 'relative', flex: 1, maxWidth: 480 }}>
            {/* Trigger */}
            <div
              onClick={() => { setSrcDropOpen(o => !o); setSrcSearch('') }}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 10px',
                border: `1px solid ${srcDropOpen ? T.primary : T.border}`, borderRadius: 3,
                background: T.surface, cursor: 'pointer', userSelect: 'none',
              }}
            >
              <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 600, color: T.textMid, background: T.tableHead, border: `1px solid ${T.border}`, borderRadius: 2, padding: '1px 5px' }}>{selectedSrc.type}</span>
              <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.text, fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedSrc.name}</span>
              <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted }}>{selectedSrc.id}</span>
              <Ico.ChevronD />
            </div>

            {/* Dropdown */}
            {srcDropOpen && (
              <div style={{
                position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4, zIndex: 50,
                background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3,
                boxShadow: '0 4px 16px rgba(9,30,66,0.18)', overflow: 'hidden',
              }}>
                {/* Search input */}
                <div style={{ padding: '8px 8px 6px', borderBottom: `1px solid ${T.border}` }}>
                  <div style={{ position: 'relative' }}>
                    <span style={{ position: 'absolute', left: 7, top: '50%', transform: 'translateY(-50%)', color: T.textMuted, display: 'flex' }}><Ico.Search /></span>
                    <input
                      autoFocus
                      value={srcSearch}
                      onChange={e => setSrcSearch(e.target.value)}
                      placeholder="Search by ID or name…"
                      style={{ width: '100%', height: 28, padding: '0 8px 0 26px', borderRadius: 3, border: `1px solid ${T.border}`, background: T.bg, color: T.text, outline: 'none', fontSize: `calc(${12}px * var(--font-scale, 1))` }}
                      onFocus={e => { e.target.style.borderColor = T.primary }}
                      onBlur={e => { e.target.style.borderColor = T.border }}
                    />
                  </div>
                </div>
                {/* Options */}
                <div style={{ maxHeight: 240, overflow: 'auto' }}>
                  {filteredSources.length === 0 && (
                    <div style={{ padding: '10px 12px', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMuted }}>No sources match.</div>
                  )}
                  {filteredSources.map(s => (
                    <div
                      key={s.id}
                      onClick={() => { if (s.id !== selectedSrcId) onInvalidate(); setSelectedSrcId(s.id); setSrcDropOpen(false); setSrcSearch('') }}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', cursor: 'pointer',
                        background: s.id === selectedSrcId ? T.rowSelected : 'transparent',
                        borderBottom: `1px solid ${T.borderLight}`,
                      }}
                      onMouseEnter={e => { if (s.id !== selectedSrcId) (e.currentTarget as HTMLElement).style.background = T.rowHover }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = s.id === selectedSrcId ? T.rowSelected : 'transparent' }}
                    >
                      <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 600, color: T.textMid, background: T.tableHead, border: `1px solid ${T.border}`, borderRadius: 2, padding: '1px 5px', flexShrink: 0 }}>{s.type}</span>
                      <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.text, fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                      <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted, flexShrink: 0 }}>{s.id}</span>
                      <StatusPill status={s.status} size="xs" />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 16, fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, flexShrink: 0 }}>
            <span>Owner: <strong style={{ color: T.text }}>{selectedSrc.owner}</strong></span>
            <span>Documents: <strong style={{ color: T.text }}>{selectedSrc.documents.toLocaleString()}</strong></span>
            <StatusPill status={selectedSrc.status} size="xs" />
          </div>
        </div>
      </div>

      {/* Source summary */}
      <div style={{ padding: '12px 20px', background: T.bg, flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3 }}>
          <div style={{ display: 'flex', borderBottom: `1px solid ${T.border}` }}>
            {(['orders', 'order_lines', 'customers'] as CollectionName[]).map(c => (
              <button key={c} onClick={() => { setTab(c); setSearch(''); setTypeFilter('') }} style={{
                padding: '8px 16px', fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: tab === c ? 600 : 400,
                color: tab === c ? T.primary : T.textMid, background: 'none', border: 'none', cursor: 'pointer',
                borderBottom: tab === c ? `2px solid ${T.primary}` : '2px solid transparent', marginBottom: -1,
              }}>
                {c} <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted, marginLeft: 4 }}>{FIELD_DATA[c].length} fields</span>
              </button>
            ))}
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16, padding: '0 16px', fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid }}>
              <span>Documents: <strong style={{ color: T.text }}>48,203</strong></span>
              <span>Sampled: <strong style={{ color: T.text }}>500</strong></span>
              <span>Last sampled: <strong style={{ color: T.text }}>2026-09-28 14:22</strong></span>
            </div>
          </div>

          <FilterBar>
            <SearchBox value={search} onChange={setSearch} placeholder="Filter by field path…" />
            <FilterSelect value={typeFilter} onChange={setTypeFilter} placeholder="All Types"
              options={[{ value: 'string', label: 'string' }, { value: 'number', label: 'number' }, { value: 'ObjectId', label: 'ObjectId' }, { value: 'date', label: 'date' }, { value: 'array', label: 'array' }]} />
            <FilterSelect value={statusFilter} onChange={setStatusFilter} placeholder="All Statuses"
              options={[{ value: 'stable', label: 'Stable' }, { value: 'new', label: 'New' }]} />
            <span style={{ marginLeft: 'auto', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>{fields.length} fields</span>
          </FilterBar>

          <table>
            <thead>
              <tr>
                <TH label="Field Path" col="path" width="30%" />
                <TH label="Data Type" col="type" width={100} />
                <TH label="Nullable" col="nullable" width={80} align="center" />
                <TH label="Repeating" col="repeating" width={90} align="center" />
                <TH label="Sample Values" col="samples" />
                <TH label="Status" col="status" width={90} />
              </tr>
            </thead>
            <tbody>
              {fields.map((f, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? T.surface : 'var(--c-fafbfc)' }}
                  onMouseEnter={e => (e.currentTarget.style.background = T.rowHover)}
                  onMouseLeave={e => (e.currentTarget.style.background = i % 2 === 0 ? T.surface : 'var(--c-fafbfc)')}>
                  <td style={{ padding: '0 12px', height: 34, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: f.repeating ? 'var(--c-7a1200)' : T.text }}>
                    {f.path}
                    {f.ambiguous && <span style={{ marginLeft: 8, fontSize: `calc(${10}px * var(--font-scale, 1))`, background: 'var(--c-fff8e6)', border: '1px solid var(--c-ffd591)', color: 'var(--c-7a4800)', padding: '1px 6px', borderRadius: 2, fontFamily: 'inherit' }}>⚠ ambiguous</span>}
                  </td>
                  <td style={{ padding: '0 12px', height: 34, borderBottom: `1px solid ${T.borderLight}` }}><TypeTag type={f.type} /></td>
                  <td style={{ padding: '0 12px', height: 34, borderBottom: `1px solid ${T.borderLight}`, textAlign: 'center', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>{f.nullable ? 'Yes' : 'No'}</td>
                  <td style={{ padding: '0 12px', height: 34, borderBottom: `1px solid ${T.borderLight}`, textAlign: 'center', fontSize: `calc(${12}px * var(--font-scale, 1))`}}>{f.repeating ? <span style={{ color: 'var(--c-7a1200)', fontWeight: 600 }}>[ ]</span> : <span style={{ color: T.textMuted }}>—</span>}</td>
                  <td style={{ padding: '0 12px', height: 34, borderBottom: `1px solid ${T.borderLight}` }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      {f.samples.map((s, j) => (
                        <span key={j} style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, fontFamily: "'Consolas','Menlo',monospace", color: T.textMid, background: T.tableHead, border: `1px solid ${T.border}`, padding: '1px 6px', borderRadius: 2 }}>{s}</span>
                      ))}
                    </div>
                  </td>
                  <td style={{ padding: '0 12px', height: 34, borderBottom: `1px solid ${T.borderLight}` }}><StatusPill status={f.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          {tab === 'orders' && (
            <div style={{ padding: '10px 14px', borderTop: `1px solid ${T.border}` }}>
              <Alert type="warning">
                <strong>Date ambiguity detected:</strong> Field <code style={{ fontFamily: 'monospace', fontSize: `calc(${11}px * var(--font-scale, 1))`}}>order_date</code> contains values like "03/04/2026" that could represent either MM/DD or DD/MM format. The field is preserved as <code style={{ fontFamily: 'monospace', fontSize: `calc(${11}px * var(--font-scale, 1))`}}>string</code> until the intended interpretation is confirmed during mapping.
              </Alert>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
