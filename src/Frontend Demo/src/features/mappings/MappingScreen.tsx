import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert, TypeTag } from '../../shared'
import type { Screen, Nav } from '../../app/types'

// ─── US5 — Mapping Studio ─────────────────────────────────────────────────────
type Mapping = { src: string; tgt: string; type: string; transform?: string; confidence?: number; ambiguous?: boolean }
const INITIAL_MAPPINGS: Record<string, Mapping[]> = {
  fact_orders: [
    { src: 'order_no', tgt: 'order_number', type: 'string', confidence: 95 },
    { src: 'customer_id', tgt: 'customer_id', type: 'ObjectId', confidence: 98 },
    { src: 'total', tgt: 'total_amount', type: 'number', transform: 'round_number(2)', confidence: 90 },
    { src: 'order_date', tgt: 'order_date', type: 'date', transform: 'date_format(MM/DD/YYYY)', confidence: 72, ambiguous: true },
    { src: 'status', tgt: 'order_status', type: 'string', transform: 'uppercase', confidence: 88 },
  ],
  fact_order_lines: [
    { src: 'lines[].sku', tgt: 'sku', type: 'string', confidence: 96 },
    { src: 'lines[].qty', tgt: 'quantity', type: 'number', confidence: 97 },
    { src: 'lines[].unit_price', tgt: 'unit_price', type: 'number', transform: 'round_number(2)', confidence: 91 },
    { src: 'lines[].discount_pct', tgt: 'discount_pct', type: 'number', confidence: 85 },
  ],
  dim_customers: [
    { src: 'customer_id', tgt: 'customer_id', type: 'ObjectId', confidence: 99 },
    { src: 'customer_name', tgt: 'customer_name', type: 'string', confidence: 97 },
  ],
}

export function MappingScreen({ onNav, onAdvance, onInvalidate }: { onNav: Nav; onAdvance: () => void; onInvalidate: () => void }) {
  const [activeTable, setActiveTable] = useState('fact_orders')
  const [mappings, setMappings] = useState(INITIAL_MAPPINGS)
  const [editing, setEditing] = useState<{ originalTarget: string; mapping: Mapping } | null>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [chatMsg, setChatMsg] = useState('')
  const [chatLog, setChatLog] = useState<{ role: 'system' | 'user'; text: string }[]>([
    { role: 'system', text: 'Mapping Assistant ready. Describe a change in plain English and I will apply it to the current pipeline.' },
  ])

  const deleteMapping = (tgt: string) => {
    onInvalidate()
    setMappings(m => ({ ...m, [activeTable]: m[activeTable].filter(x => x.tgt !== tgt) }))
  }

  const saveMapping = () => {
    if (!editing || !editing.mapping.tgt.trim()) return
    onInvalidate()
    setMappings(current => ({
      ...current,
      [activeTable]: current[activeTable].map(mapping =>
        mapping.tgt === editing.originalTarget ? { ...editing.mapping, tgt: editing.mapping.tgt.trim(), transform: editing.mapping.transform?.trim() || undefined, confidence: undefined } : mapping
      ),
    }))
    setEditing(null)
  }

  const sendMsg = () => {
    if (!chatMsg.trim()) return
    onInvalidate()
    const msg = chatMsg; setChatMsg('')
    setChatLog(l => [...l, { role: 'user', text: msg }])
    setTimeout(() => setChatLog(l => [...l, { role: 'system', text: `Received: "${msg}". In production, this would apply a bounded natural-language mapping change to the selected pipeline. This is a prototype demo.` }]), 800)
  }

  const tables = Object.keys(mappings)
  const rows = mappings[activeTable]

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg }}>
      <PageHeader
        title="Mapping Studio — AMER_Orders_2026Q3.xlsx"
        subtitle="Define and verify source-to-warehouse field mappings before loading"
        breadcrumb={['Data Sources', 'SRC-0041', 'AI Routing', 'Mapping Studio']}
        actions={
          <>
            <Btn variant="secondary" onClick={() => setChatOpen(o => !o)}><Ico.Sparkle /> Mapping Assistant</Btn>
            <Btn variant="primary" onClick={onAdvance}><Ico.ArrowR /> Save &amp; Continue</Btn>
          </>
        }
      />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Main area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Table tabs */}
          <div style={{ display: 'flex', background: T.surface, borderBottom: `1px solid ${T.border}`, flexShrink: 0 }}>
            {tables.map(t => (
              <button key={t} onClick={() => setActiveTable(t)} style={{
                padding: '10px 18px', fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: activeTable === t ? 600 : 400,
                color: activeTable === t ? T.primary : T.textMid, background: 'none', border: 'none',
                cursor: 'pointer', borderBottom: activeTable === t ? `2px solid ${T.primary}` : '2px solid transparent',
                marginBottom: -1,
              }}>
                {t}
                <span style={{ marginLeft: 6, fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted, fontWeight: 400 }}>({mappings[t].length})</span>
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Mappings table */}
            <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600 }}>Field Mappings — <span style={{ fontFamily: 'monospace', fontSize: `calc(${12}px * var(--font-scale, 1))`}}>{activeTable}</span></span>
                <Btn variant="secondary"><Ico.Plus /> Add Mapping</Btn>
              </div>
              <table>
                <thead>
                  <tr>
                    <TH label="Source Field" col="src" width="28%" />
                    <TH label="" col="a" width={32} />
                    <TH label="Target Column" col="tgt" width="25%" />
                    <TH label="Data Type" col="type" width={100} />
                    <TH label="Transform Rule" col="transform" />
                    <TH label="Confidence" col="confidence" width={100} align="right" />
                    <TH label="" col="actions" width={80} />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((m, i) => (
                    <TR key={m.tgt}
                      actions={<>
                        <Btn variant="ghost" onClick={() => setEditing({ originalTarget: m.tgt, mapping: { ...m } })}><Ico.Edit /> Edit</Btn>
                        <Btn variant="ghost" onClick={() => deleteMapping(m.tgt)}><Ico.Trash /></Btn>
                      </>}>
                      <td style={{ padding: '0 12px', height: 38, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: T.text }}>{m.src}</td>
                      <td style={{ padding: '0 4px', height: 38, borderBottom: `1px solid ${T.borderLight}`, textAlign: 'center', color: T.textMuted }}><Ico.ArrowR /></td>
                      <td style={{ padding: '0 12px', height: 38, fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${12}px * var(--font-scale, 1))`, borderBottom: `1px solid ${T.borderLight}`, color: T.textMid }}>{m.tgt}</td>
                      <td style={{ padding: '0 12px', height: 38, borderBottom: `1px solid ${T.borderLight}` }}><TypeTag type={m.type} /></td>
                      <td style={{ padding: '0 12px', height: 38, borderBottom: `1px solid ${T.borderLight}` }}>
                        {m.ambiguous
                          ? <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, background: 'var(--c-fff8e6)', border: '1px solid var(--c-ffd591)', color: 'var(--c-7a4800)', padding: '1px 6px', borderRadius: 2 }}>⚠ Confirm date format</span>
                          : m.transform
                            ? <span style={{ fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${11}px * var(--font-scale, 1))`, color: 'var(--c-5925dc)', background: 'var(--c-f4f3ff)', border: '1px solid var(--c-c9b8fe)', padding: '1px 6px', borderRadius: 2 }}>{m.transform}</span>
                            : <span style={{ color: T.textMuted, fontSize: `calc(${12}px * var(--font-scale, 1))`}}>—</span>}
                      </td>
                      <td style={{ padding: '0 12px', height: 38, borderBottom: `1px solid ${T.borderLight}`, textAlign: 'right' }}>
                        <span style={{ fontWeight: 700, fontSize: `calc(${12}px * var(--font-scale, 1))`, color: m.confidence === undefined ? T.textMuted : m.confidence >= 90 ? 'var(--c-027a48)' : m.confidence >= 75 ? 'var(--c-b54708)' : 'var(--c-b42318)' }}>
                          {m.confidence === undefined ? 'N/A' : `${m.confidence}%`}
                        </span>
                      </td>
                    </TR>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Unmapped fields */}
            {activeTable === 'fact_orders' && (
              <Panel title="Unmapped Source Fields" noPad>
                <div style={{ padding: '10px 14px', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {['shipping_address', 'shipping_address.city', 'shipping_address.zip', 'tags'].map(f => (
                    <div key={f} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, border: `1px solid ${T.border}`, borderRadius: 2, padding: '3px 8px', fontSize: `calc(${12}px * var(--font-scale, 1))`, fontFamily: "'Consolas','Menlo',monospace", color: T.textMid, background: T.tableHead }}>
                      {f}
                      <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--link-color)', display: 'flex', padding: 0 }}><Ico.Plus /></button>
                    </div>
                  ))}
                </div>
              </Panel>
            )}
          </div>
        </div>

        {/* Assistant panel */}
        {chatOpen && (
          <div style={{ width: 300, borderLeft: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column', background: T.surface, flexShrink: 0 }}>
            <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600 }}>Mapping Assistant</span>
              <button onClick={() => setChatOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: T.textMid, display: 'flex' }}><Ico.X /></button>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {chatLog.map((m, i) => (
                <div key={i} style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, lineHeight: 1.5, padding: '8px 10px', borderRadius: 3, background: m.role === 'user' ? T.rowSelected : T.tableHead, border: `1px solid ${T.border}`, color: T.text, alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '90%' }}>{m.text}</div>
              ))}
            </div>
            <div style={{ padding: 10, borderTop: `1px solid ${T.border}`, display: 'flex', gap: 6 }}>
              <input value={chatMsg} onChange={e => setChatMsg(e.target.value)} onKeyDown={e => e.key === 'Enter' && sendMsg()}
                placeholder="Describe a mapping change…"
                style={{ flex: 1, height: 30, padding: '0 8px', border: `1px solid ${T.border}`, borderRadius: 3, outline: 'none', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.text }} />
              <Btn variant="primary" onClick={sendMsg}><Ico.ArrowR /></Btn>
            </div>
          </div>
        )}
      </div>
      {editing && (
        <Modal title={`Edit Mapping — ${editing.mapping.src}`} onClose={() => setEditing(null)} width={520}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Alert type="info">Review the source field and manually update where and how it is written to <strong>{activeTable}</strong>.</Alert>
            <div style={{ background: T.tableHead, border: `1px solid ${T.border}`, borderRadius: 3, padding: '10px 12px' }}>
              <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, marginBottom: 3 }}>SOURCE FIELD</div>
              <div style={{ fontFamily: "'Consolas','Menlo',monospace", fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text }}>{editing.mapping.src}</div>
            </div>
            <TextInput label="Target Column" value={editing.mapping.tgt} onChange={tgt => setEditing(current => current ? { ...current, mapping: { ...current.mapping, tgt } } : current)} placeholder="target_column" />
            <SelectInput label="Data Type" value={editing.mapping.type} onChange={type => setEditing(current => current ? { ...current, mapping: { ...current.mapping, type } } : current)}
              options={['string', 'number', 'date', 'ObjectId', 'boolean', 'array'].map(value => ({ value, label: value }))} />
            <TextInput label="Transform Rule" value={editing.mapping.transform ?? ''} onChange={transform => setEditing(current => current ? { ...current, mapping: { ...current.mapping, transform } } : current)} placeholder="e.g. uppercase or date_format(YYYY-MM-DD)" />
            <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted, marginTop: -4 }}>Confidence scores are system-generated. Saving a manual mapping marks this value as N/A.</div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, borderTop: `1px solid ${T.border}`, paddingTop: 16 }}>
              <Btn variant="secondary" onClick={() => setEditing(null)}>Cancel</Btn>
              <Btn variant="primary" onClick={saveMapping} disabled={!editing.mapping.tgt.trim()}><Ico.Check /> Save Mapping</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
