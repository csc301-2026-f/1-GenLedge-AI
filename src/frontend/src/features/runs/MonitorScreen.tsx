import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert } from '../../shared'
import type { Screen, Nav } from '../../app/types'

// ─── US7 — Pipelines & Monitor ────────────────────────────────────────────────
const PIPELINES = [
  { id: 'PL-0041', name: 'AMER_Orders_2026Q3 → warehouse', source: 'SRC-0041', schedule: 'Every 6h', nextRun: '2026-09-29 12:00', status: 'active', lastStatus: 'success', owner: 'J. Rivera', confidence: 94 },
  { id: 'PL-0038', name: 'CustomerMaster_export → dim_customers', source: 'SRC-0038', schedule: 'Daily 02:00 UTC', nextRun: '2026-09-30 02:00', status: 'active', lastStatus: 'success', owner: 'M. Chen', confidence: 91 },
  { id: 'PL-0040', name: 'ProductCatalog_v3 → dim_products', source: 'SRC-0040', schedule: 'Manual', nextRun: '—', status: 'draft', lastStatus: null, owner: 'S. Okonkwo', confidence: 76 },
  { id: 'PL-0031', name: 'ERP_Live_Production → fact_transactions', source: 'SRC-0031', schedule: 'Every 15m', nextRun: '2026-09-29 09:15', status: 'parked', lastStatus: 'failed', owner: 'IT Ops', confidence: 68 },
  { id: 'PL-0035', name: 'HubSpot_Contacts → dim_contacts', source: 'SRC-0035', schedule: 'Daily 23:00 UTC', nextRun: '2026-09-29 23:00', status: 'active', lastStatus: 'success', owner: 'K. Vasquez', confidence: 88 },
]

const RUN_HISTORY = [
  { id: 'RUN-20260929-0091', pipeline: 'PL-0041', status: 'success', started: '2026-09-29 09:14:32', duration: '1m 42s', extracted: 48203, loaded: 91847, error: null },
  { id: 'RUN-20260929-0088', pipeline: 'PL-0038', status: 'success', started: '2026-09-29 02:00:04', duration: '0m 12s', extracted: 5847, loaded: 5847, error: null },
  { id: 'RUN-20260929-0085', pipeline: 'PL-0035', status: 'success', started: '2026-09-28 23:00:01', duration: '0m 44s', extracted: 12400, loaded: 12400, error: null },
  { id: 'RUN-20260929-0083', pipeline: 'PL-0031', status: 'failed', started: '2026-09-28 22:00:00', duration: '0m 08s', extracted: 0, loaded: 0, error: 'Connection refused: MongoDB replica set primary unavailable' },
  { id: 'RUN-20260929-0081', pipeline: 'PL-0031', status: 'failed', started: '2026-09-28 21:52:00', duration: '0m 08s', extracted: 0, loaded: 0, error: 'Connection refused: MongoDB replica set primary unavailable' },
  { id: 'RUN-20260929-0078', pipeline: 'PL-0041', status: 'success', started: '2026-09-28 21:14:18', duration: '1m 41s', extracted: 47102, loaded: 89811, error: null },
  { id: 'RUN-20260929-0076', pipeline: 'PL-0031', status: 'failed', started: '2026-09-28 21:00:00', duration: '0m 09s', extracted: 0, loaded: 0, error: 'Connection refused: MongoDB replica set primary unavailable' },
  { id: 'RUN-20260929-0073', pipeline: 'PL-0038', status: 'success', started: '2026-09-28 02:00:02', duration: '0m 11s', extracted: 5821, loaded: 5821, error: null },
]

export function MonitorScreen({ onNav }: { onNav: Nav }) {
  const [histSearch, setHistSearch] = useState('')
  const [histStatus, setHistStatus] = useState('')
  const [histPipeline, setHistPipeline] = useState('')
  const [page, setPage] = useState(1)
  const [showSchedule, setShowSchedule] = useState(false)
  const [schedTarget, setSchedTarget] = useState('')
  const [schedType, setSchedType] = useState<'interval' | 'cron'>('interval')
  const [schedVal, setSchedVal] = useState('360')
  const [schedTz, setSchedTz] = useState('UTC')
  const [histPage, setHistPage] = useState(1)
  const HIST_PAGE = 6

  const filteredHistory = useMemo(() => {
    let d = [...RUN_HISTORY]
    if (histSearch) d = d.filter(r => r.id.includes(histSearch) || r.pipeline.includes(histSearch))
    if (histStatus) d = d.filter(r => r.status === histStatus)
    if (histPipeline) d = d.filter(r => r.pipeline === histPipeline)
    return d
  }, [histSearch, histStatus, histPipeline])

  const pageSize = 10
  const pagedHistory = filteredHistory.slice((page - 1) * pageSize, page * pageSize)

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg, overflow: 'auto' }}>
      <PageHeader
        title="Pipelines & Run Monitor"
        subtitle="Manage pipeline schedules and inspect execution history"
      />

      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Parked alert */}
        <Alert type="warning">
          <strong>Pipeline PL-0031 (ERP_Live_Production → fact_transactions) has been parked</strong> after 5 consecutive failures. Automatic execution is suspended. Backoff delays applied: 1, 2, 4, 8 min. Resolve the MongoDB connectivity issue, then manually re-activate the pipeline.
        </Alert>

        {/* Pipelines table */}
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600 }}>Pipelines ({PIPELINES.length})</span>
          </div>
          <table>
            <thead>
              <tr>
                <TH label="Pipeline ID" col="id" width={110} />
                <TH label="Pipeline Name" col="name" />
                <TH label="Operator" col="owner" width={120} />
                <TH label="Confidence Score" col="confidence" width={130} align="right" />
                <TH label="Schedule" col="schedule" width={150} />
                <TH label="Next Run" col="nextRun" width={170} />
                <TH label="Status" col="status" width={100} />
                <TH label="Last Run" col="lastStatus" width={100} />
                <th style={{ width: 160, background: T.tableHead, borderBottom: `1px solid ${T.border}` }} />
              </tr>
            </thead>
            <tbody>
              {PIPELINES.map(row => (
                <TR key={row.id}
                  actions={<>
                    <Btn variant="ghost" onClick={() => { setSchedTarget(row.id); setShowSchedule(true) }}><Ico.Clock /> Schedule</Btn>
                    <Btn variant="ghost"><Ico.Play /> Run</Btn>
                  </>}>
                  <TD mono muted>{row.id}</TD>
                  <TD><span style={{ color: T.primary }}>{row.name}</span></TD>
                  <TD muted>{row.owner}</TD>
                  <TD mono right><span style={{ fontWeight: 700, color: row.confidence >= 90 ? 'var(--c-027a48)' : row.confidence >= 75 ? 'var(--c-b54708)' : 'var(--c-b42318)' }}>{row.confidence}%</span></TD>
                  <TD mono muted>{row.schedule}</TD>
                  <TD mono muted>{row.nextRun}</TD>
                  <TD><StatusPill status={row.status} /></TD>
                  <TD>{row.lastStatus ? <StatusPill status={row.lastStatus} /> : <span style={{ color: T.textMuted }}>—</span>}</TD>
                </TR>
              ))}
            </tbody>
          </table>
        </div>

        {/* Run history */}
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden' }}>
          <FilterBar>
            <span style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text, marginRight: 8 }}>Run History</span>
            <SearchBox value={histSearch} onChange={v => { setHistSearch(v); setPage(1) }} placeholder="Search run ID or pipeline…" />
            <FilterSelect value={histStatus} onChange={v => { setHistStatus(v); setPage(1) }} placeholder="All Statuses"
              options={[{ value: 'success', label: 'Success' }, { value: 'failed', label: 'Failed' }, { value: 'running', label: 'Running' }]} />
            <FilterSelect value={histPipeline} onChange={v => { setHistPipeline(v); setPage(1) }} placeholder="All Pipelines"
              options={PIPELINES.map(p => ({ value: p.id, label: p.id }))} />
            {(histSearch || histStatus || histPipeline) && <Btn variant="ghost" onClick={() => { setHistSearch(''); setHistStatus(''); setHistPipeline('') }}>Clear</Btn>}
            <span style={{ marginLeft: 'auto', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>{filteredHistory.length} runs</span>
          </FilterBar>
          <table>
            <thead>
              <tr>
                <TH label="Run ID" col="id" width={200} />
                <TH label="Pipeline" col="pipeline" width={100} />
                <TH label="Status" col="status" width={100} />
                <TH label="Started" col="started" width={175} />
                <TH label="Duration" col="duration" width={90} align="right" />
                <TH label="Extracted" col="extracted" width={100} align="right" />
                <TH label="Loaded" col="loaded" width={100} align="right" />
                <TH label="Error" col="error" />
              </tr>
            </thead>
            <tbody>
              {pagedHistory.map(row => (
                <TR key={row.id}>
                  <TD mono muted>{row.id}</TD>
                  <TD mono muted>{row.pipeline}</TD>
                  <TD><StatusPill status={row.status} /></TD>
                  <TD mono muted nowrap>{row.started}</TD>
                  <TD mono right>{row.duration}</TD>
                  <TD mono right muted>{row.extracted > 0 ? row.extracted.toLocaleString() : '—'}</TD>
                  <TD mono right muted>{row.loaded > 0 ? row.loaded.toLocaleString() : '—'}</TD>
                  <td style={{ padding: '0 12px', height: 38, fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: 'var(--c-b42318)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.error ?? <span style={{ color: T.textMuted }}>—</span>}
                  </td>
                </TR>
              ))}
            </tbody>
          </table>
          <Pager total={filteredHistory.length} page={page} pageSize={pageSize} onPage={setPage} />
        </div>
      </div>

      {showSchedule && (
        <Modal title={`Set Schedule — ${schedTarget}`} onClose={() => setShowSchedule(false)} width={440}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', borderRadius: 3, border: `1px solid ${T.border}`, overflow: 'hidden' }}>
              {(['interval', 'cron'] as const).map(t => (
                <button key={t} onClick={() => setSchedType(t)} style={{
                  flex: 1, height: 32, fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 500, cursor: 'pointer', border: 'none',
                  background: schedType === t ? T.primary : T.surface,
                  color: schedType === t ? '#fff' : T.textMid,
                  borderRight: t === 'interval' ? `1px solid ${T.border}` : 'none',
                }}>{t === 'interval' ? 'Interval' : 'Cron Expression'}</button>
              ))}
            </div>

            {schedType === 'interval' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <TextInput label="Interval (minutes) — minimum 5 minutes" value={schedVal} onChange={setSchedVal} type="number" />
                <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid }}>Next run: approximately {Math.round(Number(schedVal) / 60 * 10) / 10}h from now</span>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <TextInput label="Cron Expression" value="0 */6 * * *" onChange={() => {}} />
                <SelectInput label="Timezone" value={schedTz} onChange={setSchedTz}
                  options={['UTC', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/London', 'Asia/Singapore', 'Asia/Tokyo'].map(v => ({ value: v, label: v }))} />
              </div>
            )}

            <Alert type="info">Pipelines that fail 5 consecutive times are automatically parked. Failures are retried with backoff delays of 1, 2, 4, and 8 minutes before parking.</Alert>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, borderTop: `1px solid ${T.border}`, paddingTop: 16 }}>
              <Btn variant="secondary" onClick={() => setShowSchedule(false)}>Cancel</Btn>
              <Btn variant="primary" onClick={() => setShowSchedule(false)}><Ico.Check /> Save Schedule</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
