import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert } from '../../shared'
import type { Screen, Nav } from '../../app/types'

// ─── US6 — Transform & Load ───────────────────────────────────────────────────
const TRANSFORMS_LIST = [
  { field: 'total', rule: 'round_number(2)', example: '2840.498  →  2840.50' },
  { field: 'order_date', rule: 'date_format(MM/DD/YYYY)', example: '03/04/2026  →  2026-03-04' },
  { field: 'status', rule: 'uppercase', example: 'fulfilled  →  FULFILLED' },
  { field: 'lines[].unit_price', rule: 'round_number(2)', example: '142.009  →  142.01' },
]

export function RunScreen({ onNav, onAdvance, onInvalidate }: { onNav: Nav; onAdvance: () => void; onInvalidate: () => void }) {
  const [phase, setPhase] = useState<'idle' | 'running' | 'done'>('idle')
  const [pct, setPct] = useState(0)
  const [log, setLog] = useState<string[]>([])

  const runNow = () => {
    onInvalidate()
    setPhase('running'); setPct(0); setLog(['[09:14:31] Pipeline RUN-20260929-0091 initiated'])
    const msgs = [
      '[09:14:32] Reading source: BATCH-1892 / orders',
      '[09:14:33] Parsed 48,203 source documents',
      '[09:14:35] Applying 4 transformation rules',
      '[09:14:48] Writing to fact_orders (48,203 rows)',
      '[09:14:52] Expanding lines[] into fact_order_lines (91,847 rows)',
      '[09:14:55] Merging dim_customers (2,340 upserts)',
      '[09:14:58] Verifying row counts and merge keys',
      '[09:15:13] Pipeline completed. 0 errors.',
    ]
    msgs.forEach((m, i) => setTimeout(() => {
      setLog(l => [...l, m])
      setPct(Math.round((i + 1) / msgs.length * 100))
      if (i === msgs.length - 1) setTimeout(() => setPhase('done'), 400)
    }, (i + 1) * 600))
  }

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, background: T.bg }}>
      <PageHeader
        title="Transform & Load — Pipeline PL-0041"
        subtitle="Review configuration, then execute the pipeline to populate warehouse tables"
        breadcrumb={['Data Sources', 'SRC-0041', 'Mapping Studio', 'Transform & Load']}
        actions={
          phase === 'done'
            ? <Btn variant="secondary" onClick={onAdvance}><Ico.Clock /> View in Monitor</Btn>
            : <Btn variant="primary" onClick={runNow} disabled={phase === 'running'}><Ico.Play />{phase === 'running' ? 'Running…' : 'Run Now'}</Btn>
        }
      />

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 20, display: 'flex', gap: 20 }}>
        {/* Left: config */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
          <Panel title="Pipeline Configuration" noPad scrollable>
            <div style={{ minWidth: 640 }}>
              {[
                ['Pipeline ID', 'PL-0041'],
                ['Source', 'AMER_Orders_2026Q3.xlsx — orders (SRC-0041)'],
                ['Target Tables', 'fact_orders, fact_order_lines, dim_customers'],
                ['Total Mappings', '11 fields mapped across 3 tables'],
                ['Merge Key', 'order_id (fact_orders), order_id + sku (fact_order_lines)'],
                ['Est. Source Documents', '48,203'],
                ['Repeating Field Expansion', 'lines[] → fact_order_lines (1:N)'],
                ['Created By', 'J. Rivera · 2026-09-29'],
              ].map(([l, v]) => <InfoRow key={l} label={l} value={v} />)}
            </div>
          </Panel>

          <Panel title="Transformation Rules" noPad scrollable>
            <table style={{ minWidth: 640 }}>
              <thead>
                <tr>
                  <TH label="Source Field" col="f" />
                  <TH label="Rule" col="r" />
                  <TH label="Example" col="e" />
                </tr>
              </thead>
              <tbody>
                {TRANSFORMS_LIST.map(t => (
                  <tr key={t.field} style={{ background: T.surface }} onMouseEnter={e => (e.currentTarget.style.background = T.rowHover)} onMouseLeave={e => (e.currentTarget.style.background = T.surface)}>
                    <td style={{ padding: '0 12px', height: 36, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: T.text }}>{t.field}</td>
                    <td style={{ padding: '0 12px', height: 36, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: 'var(--c-5925dc)' }}>{t.rule}</td>
                    <td style={{ padding: '0 12px', height: 36, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: T.textMid }}>{t.example}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        {/* Right: execution */}
        <div style={{ width: 400, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Progress / results */}
          {phase === 'idle' && (
            <Panel title="Execution">
              <div style={{ textAlign: 'center', padding: '24px 0', color: T.textMid }}>
                <div style={{ marginBottom: 12 }}><Ico.Play /></div>
                <p style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`}}>Click <strong>Run Now</strong> to begin extraction and load.</p>
                <p style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted, marginTop: 6 }}>A new snapshot is created before the previous is replaced. A failed run will not leave the warehouse in a partial state.</p>
              </div>
            </Panel>
          )}

          {(phase === 'running' || phase === 'done') && (
            <Panel title={phase === 'running' ? 'Running…' : 'Completed — RUN-20260929-0091'} noPad>
              {phase === 'running' && (
                <div style={{ padding: '12px 14px', borderBottom: `1px solid ${T.border}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: `calc(${12}px * var(--font-scale, 1))`}}>
                    <span style={{ color: T.textMid }}>Progress</span>
                    <span style={{ fontWeight: 600 }}>{pct}%</span>
                  </div>
                  <div style={{ height: 6, background: T.tableHead, borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: '100%', background: T.primary, borderRadius: 2, width: `${pct}%`, transition: 'width 0.3s' }} />
                  </div>
                </div>
              )}
              {phase === 'done' && (
                <div style={{ padding: '12px 14px', borderBottom: `1px solid ${T.border}`, background: 'var(--c-ecfdf3)' }}>
                  <div style={{ display: 'flex', gap: 24 }}>
                    {[{ label: 'Extracted', value: '48,203' }, { label: 'Loaded', value: '91,847' }, { label: 'Errors', value: '0' }].map(s => (
                      <div key={s.label}>
                        <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: 'var(--c-027a48)', marginBottom: 2 }}>{s.label}</div>
                        <div style={{ fontSize: `calc(${20}px * var(--font-scale, 1))`, fontWeight: 700, color: s.label === 'Errors' ? (s.value === '0' ? 'var(--c-027a48)' : 'var(--c-b42318)') : T.text }}>{s.value}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, marginTop: 8 }}>Duration: 1m 42s · 2026-09-29 09:14:32 UTC</div>
                </div>
              )}
              <div style={{ padding: '10px 14px', fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${11}px * var(--font-scale, 1))`, color: 'var(--c-1d4f25)', background: 'var(--c-f6fef9)', maxHeight: 240, overflow: 'auto' }}>
                {log.map((l, i) => <div key={i} style={{ lineHeight: 1.8, color: i === log.length - 1 && phase === 'done' ? 'var(--c-027a48)' : T.textMid }}>{l}</div>)}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
