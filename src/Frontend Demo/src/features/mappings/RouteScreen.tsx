import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert, TypeTag } from '../../shared'
import type { Screen, Nav } from '../../app/types'

// ─── US4 — AI Routing ─────────────────────────────────────────────────────────
const ROUTE_DATA = [
  {
    table: 'fact_orders', isNew: false, confidence: 92, mergeKey: 'order_id',
    reason: 'Top-level order document fields map cleanly to existing fact_orders table. Recommend reuse with 5 new columns held for approval.',
    fields: [
      { src: 'order_no', tgt: 'order_number', type: 'string' },
      { src: 'customer_id', tgt: 'customer_id', type: 'ObjectId' },
      { src: 'total', tgt: 'total_amount', type: 'number' },
      { src: 'order_date', tgt: 'order_date', type: '!ambiguous' },
      { src: 'status', tgt: 'order_status', type: 'string' },
    ],
  },
  {
    table: 'fact_order_lines', isNew: true, confidence: 87, mergeKey: 'order_id + sku',
    reason: 'Repeating lines[] array should be expanded: each array element produces one row in a new fact_order_lines table, linked by order_id.',
    fields: [
      { src: 'lines[].sku', tgt: 'sku', type: 'string' },
      { src: 'lines[].qty', tgt: 'quantity', type: 'number' },
      { src: 'lines[].unit_price', tgt: 'unit_price', type: 'number' },
      { src: 'lines[].discount_pct', tgt: 'discount_pct', type: 'number' },
    ],
  },
  {
    table: 'dim_customers', isNew: false, confidence: 78, mergeKey: 'customer_id',
    reason: 'customer_id and customer_name link to existing dim_customers. Low confidence due to incomplete customer attribute data in this source.',
    fields: [
      { src: 'customer_id', tgt: 'customer_id', type: 'ObjectId' },
      { src: 'customer_name', tgt: 'customer_name', type: 'string' },
    ],
  },
]

export function RouteScreen({ onNav, onAdvance, onInvalidate }: { onNav: Nav; onAdvance: () => void; onInvalidate: () => void }) {
  const [decisions, setDecisions] = useState<Record<string, 'accept' | 'reject' | null>>({})
  const decide = (table: string, dec: 'accept' | 'reject') => {
    onInvalidate()
    setDecisions(d => ({ ...d, [table]: d[table] === dec ? null : dec }))
  }

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg }}>
      <PageHeader
        title="AI Routing Results — AMER_Orders_2026Q3.xlsx / orders"
        subtitle="AI-proposed warehouse destinations. Review each proposal and accept or reject before proceeding."
        breadcrumb={['Data Sources', 'SRC-0041', 'Schema Discovery', 'AI Routing']}
        actions={
          <Btn variant="primary" onClick={() => { setDecisions(Object.fromEntries(ROUTE_DATA.map(r => [r.table, 'accept']))); setTimeout(onAdvance, 300) }}>
            <Ico.Check /> Accept All & Open Mapping Studio
          </Btn>
        }
      />

      <div style={{ padding: '12px 20px', flexShrink: 0 }}>
        <Alert type="info">
          The AI model received field paths, inferred types, repeating-field status, and up to 3 sample values per field. No full row data, database credentials, connection strings, or client identifiers were sent to the model.
        </Alert>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '0 20px 20px' }}>
        {/* Decisions table */}
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden', marginBottom: 16 }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text }}>Proposed Warehouse Routing ({ROUTE_DATA.length} proposals)</span>
            <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>
              {Object.values(decisions).filter(d => d === 'accept').length} accepted · {Object.values(decisions).filter(d => d === 'reject').length} rejected
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <TH label="Target Table" col="table" />
                <TH label="Table Action" col="new" width={110} />
                <TH label="Confidence" col="confidence" width={100} align="right" />
                <TH label="Merge Key" col="mergeKey" width={180} />
                <TH label="Fields Mapped" col="fields" width={110} align="right" />
                <TH label="Decision" col="decision" width={160} />
              </tr>
            </thead>
            <tbody>
              {ROUTE_DATA.map(row => (
                <TR key={row.table} selected={decisions[row.table] === 'accept'}>
                  <TD><span style={{ fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text }}>{row.table}</span></TD>
                  <TD><StatusPill status={row.isNew ? 'proposed' : 'connected'} /></TD>
                  <TD mono right>
                    <span style={{ fontWeight: 700, color: row.confidence >= 85 ? 'var(--c-027a48)' : row.confidence >= 70 ? 'var(--c-b54708)' : 'var(--c-b42318)' }}>{row.confidence}%</span>
                  </TD>
                  <TD mono>{row.mergeKey}</TD>
                  <TD mono right>{row.fields.length}</TD>
                  <td style={{ padding: '0 12px', height: 38, borderBottom: `1px solid ${T.borderLight}` }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Btn variant={decisions[row.table] === 'accept' ? 'primary' : 'secondary'} onClick={() => decide(row.table, 'accept')}><Ico.Check /> Accept</Btn>
                      <Btn variant={decisions[row.table] === 'reject' ? 'danger' : 'ghost'} onClick={() => decide(row.table, 'reject')}><Ico.X /> Reject</Btn>
                    </div>
                  </td>
                </TR>
              ))}
            </tbody>
          </table>
        </div>

        {/* Field assignment detail */}
        {ROUTE_DATA.map(row => (
          <div key={row.table} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden', marginBottom: 12, opacity: decisions[row.table] === 'reject' ? 0.5 : 1 }}>
            <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 12, background: decisions[row.table] === 'accept' ? 'var(--c-ecfdf3)' : T.tableHead }}>
              <span style={{ fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 700, color: T.text }}>{row.table}</span>
              {row.isNew && <StatusPill status="proposed" />}
              {decisions[row.table] === 'accept' && <StatusPill status="accept" />}
              <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid, flex: 1 }}>{row.reason}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <TH label="Source Field" col="src" width="40%" />
                  <TH label="" col="arrow" width={32} />
                  <TH label="Target Column" col="tgt" />
                  <TH label="Type" col="type" width={100} />
                </tr>
              </thead>
              <tbody>
                {row.fields.map(f => (
                  <tr key={f.src} style={{ background: T.surface }} onMouseEnter={e => (e.currentTarget.style.background = T.rowHover)} onMouseLeave={e => (e.currentTarget.style.background = T.surface)}>
                    <td style={{ padding: '0 12px', height: 34, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: T.text }}>{f.src}</td>
                    <td style={{ padding: '0 4px', height: 34, borderBottom: `1px solid ${T.borderLight}`, color: T.textMuted, textAlign: 'center' }}><Ico.ArrowR /></td>
                    <td style={{ padding: '0 12px', height: 34, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: T.textMid }}>{f.tgt}</td>
                    <td style={{ padding: '0 12px', height: 34, borderBottom: `1px solid ${T.borderLight}` }}>
                      {f.type === '!ambiguous'
                        ? <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, background: 'var(--c-fff8e6)', border: '1px solid var(--c-ffd591)', color: 'var(--c-7a4800)', padding: '1px 6px', borderRadius: 2, fontWeight: 600 }}>⚠ Review in mapping</span>
                        : <TypeTag type={f.type} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  )
}
