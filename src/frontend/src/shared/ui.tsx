import React, { useState, useRef } from 'react'
import { createPortal } from 'react-dom'

export type SortDir = 'asc' | 'desc' | null

export const cx = (...c: (string | false | undefined | null)[]) => c.filter(Boolean).join(' ')

// ─── Design tokens ────────────────────────────────────────────────────────────
export const T = {
  sidebar: 'var(--c-1e3a5f)',
  sidebarBorder: 'rgba(255,255,255,0.08)',
  sidebarText: 'var(--c-b0bec5)',
  sidebarActive: 'rgba(1,118,211,0.25)',
  sidebarActiveBorder: 'var(--c-4fa3e0)',
  primary: 'var(--c-0176d3)',
  primaryHover: 'var(--c-014486)',
  surface: 'var(--c-ffffff)',
  bg: 'var(--c-f4f5f7)',
  border: 'var(--c-dfe1e6)',
  borderLight: 'var(--c-ebecf0)',
  text: 'var(--c-172b4d)',
  textMid: 'var(--c-5e6c84)',
  textMuted: 'var(--c-97a0af)',
  tableHead: 'var(--c-f4f5f7)',
  rowHover: 'var(--c-f4f5f7)',
  rowSelected: 'var(--c-deebff)',
}

// ─── Status indicators ────────────────────────────────────────────────────────
export type StatusKind = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'purple'

export const STATUS_MAP: Record<string, StatusKind> = {
  ready: 'success', success: 'success', active: 'success', connected: 'success',
  parked: 'warning', pending: 'warning', scheduled: 'warning',
  failed: 'error', error: 'error',
  running: 'info', ingesting: 'info', processing: 'info',
  draft: 'neutral', manual: 'neutral', new: 'purple', proposed: 'purple',
}

export const STATUS_STYLE: Record<StatusKind, [string, string, string]> = {
  success: ['var(--c-027a48)', 'var(--c-ecfdf3)', 'var(--c-abefc6)'],
  warning: ['var(--c-b54708)', 'var(--c-fffaeb)', 'var(--c-fedf89)'],
  error:   ['var(--c-b42318)', 'var(--c-fef3f2)', 'var(--c-fecdca)'],
  info:    ['var(--c-1849a9)', 'var(--c-eff8ff)', 'var(--c-b2ddff)'],
  neutral: ['var(--c-344054)', 'var(--c-f9fafb)', 'var(--c-eaecf0)'],
  purple:  ['var(--c-5925dc)', 'var(--c-f4f3ff)', 'var(--c-c9b8fe)'],
}

export const DOT_COLOR: Record<StatusKind, string> = {
  success: '#12B76A', warning: '#F79009', error: '#F04438',
  info: '#2E90FA', neutral: '#98A2B3', purple: '#7A5AF8',
}

export function StatusPill({ status, size = 'sm' }: { status: string; size?: 'xs' | 'sm' }) {
  const kind = STATUS_MAP[status.toLowerCase()] ?? 'neutral'
  const [text, bg, border] = STATUS_STYLE[kind]
  const dot = DOT_COLOR[kind]
  const label = status.charAt(0).toUpperCase() + status.slice(1)
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: size === 'xs' ? '0 6px' : '1px 7px',
      borderRadius: 3, background: bg, border: `1px solid ${border}`,
      color: text, fontSize: `calc(${size === 'xs' ? 11 : 11}px * var(--font-scale, 1))`, fontWeight: 500, whiteSpace: 'nowrap',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
      {label}
    </span>
  )
}

const TYPE_COLOR: Record<string, string> = {
  string: 'var(--c-0052a4)', number: 'var(--c-006632)', ObjectId: 'var(--c-5925dc)', date: 'var(--c-7a4800)', array: 'var(--c-7a1200)', object: 'var(--c-344054)', boolean: 'var(--c-6b0069)',
}

export function TypeTag({ type }: { type: string }) {
  const color = TYPE_COLOR[type] ?? 'var(--c-344054)'
  return <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 600, color, background: `${color}14`, border: `1px solid ${color}30`, padding: '1px 6px', borderRadius: 2 }}>{type}</span>
}

// ─── Buttons ──────────────────────────────────────────────────────────────────
export type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link'

export function Btn({
  children, onClick, variant = 'secondary', disabled, type = 'button', className,
}: {
  children: React.ReactNode; onClick?: () => void; variant?: BtnVariant
  disabled?: boolean; type?: 'button' | 'submit'; className?: string
}) {
  const base: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    height: 30, padding: '0 11px', borderRadius: 3, fontSize: `calc(${12}px * var(--font-scale, 1))`,
    fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid transparent', transition: 'background 0.12s, border-color 0.12s',
    opacity: disabled ? 0.5 : 1, whiteSpace: 'nowrap',
  }
  const styles: Record<BtnVariant, React.CSSProperties> = {
    primary:   { background: T.primary, color: '#fff', borderColor: T.primary },
    secondary: { background: T.surface, color: T.text, borderColor: T.border },
    ghost:     { background: 'transparent', color: T.textMid, borderColor: 'transparent' },
    danger:    { background: 'var(--c-fef3f2)', color: 'var(--c-b42318)', borderColor: 'var(--c-fecdca)' },
    link:      { background: 'transparent', color: 'var(--link-color)', borderColor: 'transparent', padding: '0 2px' },
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={className}
      style={{ ...base, ...styles[variant] }}>
      {children}
    </button>
  )
}

// ─── Form controls ────────────────────────────────────────────────────────────
export function TextInput({
  value, onChange, placeholder, label, type = 'text', width,
}: {
  value: string; onChange: (v: string) => void; placeholder?: string
  label?: string; type?: string; width?: number
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width }}>
      {label && <label style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 500, color: T.textMid }}>{label}</label>}
      <input
        type={type} value={value} placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        style={{
          height: 30, padding: '0 8px', borderRadius: 3,
          border: `1px solid ${T.border}`, background: T.surface,
          color: T.text, outline: 'none', width: '100%',
        }}
        onFocus={e => { e.target.style.borderColor = T.primary }}
        onBlur={e => { e.target.style.borderColor = T.border }}
      />
    </div>
  )
}

export function SelectInput({
  value, onChange, options, label, width,
}: {
  value: string; onChange: (v: string) => void
  options: { value: string; label: string }[]
  label?: string; width?: number
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width }}>
      {label && <label style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 500, color: T.textMid }}>{label}</label>}
      <select value={value} onChange={e => onChange(e.target.value)} style={{
        height: 30, padding: '0 8px', borderRadius: 3,
        border: `1px solid ${T.border}`, background: T.surface,
        color: T.text, outline: 'none', width: '100%', cursor: 'pointer',
      }}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

// ─── Icons ────────────────────────────────────────────────────────────────────
export const Ico = {
  Database:    () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>,
  Upload:      () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
  Search:      () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  ChevronR:    () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>,
  ChevronL:    () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>,
  ChevronD:    () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>,
  Sort:        () => <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/></svg>,
  SortUp:      () => <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="18 15 12 9 6 15"/></svg>,
  SortDown:    () => <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>,
  Play:        () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>,
  Check:       () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
  X:           () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  Plus:        () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  Refresh:     () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>,
  ArrowR:      () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>,
  Edit:        () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
  Trash:       () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>,
  LogOut:      () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>,
  Settings:    () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  Users:       () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  Bell:        () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>,
  Help:        () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Sparkle:     () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48 2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48 2.83-2.83"/></svg>,
  Map:         () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/></svg>,
  Clock:       () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
  Warning:     () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Lock:        () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>,
}

// ─── Pagination ───────────────────────────────────────────────────────────────
export function Pager({
  total, page, pageSize, onPage,
}: { total: number; page: number; pageSize: number; onPage: (p: number) => void }) {
  const totalPages = Math.ceil(total / pageSize)
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderTop: `1px solid ${T.border}`, background: T.surface, flexShrink: 0 }}>
      <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>
        Showing {from}–{to} of {total.toLocaleString()} records
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {(() => {
          const seen = new Set<number>()
          const pages: (number | 'ellipsis-left' | 'ellipsis-right')[] = []
          const add = (n: number) => { if (n >= 1 && n <= totalPages && !seen.has(n)) { seen.add(n); pages.push(n) } }
          add(1); add(2); add(3)
          const before = pages.length
          ;[page - 1, page, page + 1].forEach(add)
          ;[totalPages - 1, totalPages].forEach(add)
          const sorted = pages.sort((a, b) => (a as number) - (b as number))
          const withEllipsis: (number | 'ellipsis-left' | 'ellipsis-right')[] = []
          sorted.forEach((n, i) => {
            if (i > 0 && (n as number) - (sorted[i - 1] as number) > 1) withEllipsis.push(i === 1 ? 'ellipsis-left' : 'ellipsis-right')
            withEllipsis.push(n)
          })
          return withEllipsis.map(p =>
            typeof p === 'string'
              ? <span key={p} style={{ padding: '0 4px', color: T.textMuted, fontSize: `calc(${12}px * var(--font-scale, 1))`}}>…</span>
              : <button key={`pg-${p}`} onClick={() => onPage(p)} style={{
                  width: 28, height: 28, borderRadius: 3, border: `1px solid ${page === p ? T.primary : T.border}`,
                  background: page === p ? T.primary : T.surface, color: page === p ? '#fff' : T.text,
                  fontSize: `calc(${12}px * var(--font-scale, 1))`, cursor: 'pointer', fontWeight: page === p ? 600 : 400,
                }}>{p}</button>
          )
        })()}
        <button onClick={() => onPage(Math.min(page + 1, totalPages))} disabled={page >= totalPages}
          style={{ width: 28, height: 28, borderRadius: 3, border: `1px solid ${T.border}`, background: T.surface, cursor: page >= totalPages ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: page >= totalPages ? 0.4 : 1 }}>
          <Ico.ChevronR />
        </button>
      </div>
    </div>
  )
}

// ─── Table sort state ─────────────────────────────────────────────────────────

export function SortIcon({ col, sortCol, sortDir }: { col: string; sortCol: string; sortDir: SortDir }) {
  if (col !== sortCol || !sortDir) return <span style={{ color: T.textMuted, opacity: 0.4 }}><Ico.Sort /></span>
  return sortDir === 'asc' ? <Ico.SortUp /> : <Ico.SortDown />
}

// ─── Column header ────────────────────────────────────────────────────────────
export function TH({
  label, col, sortCol, sortDir, onSort, width, align = 'left',
}: {
  label: string; col: string; sortCol?: string; sortDir?: SortDir
  onSort?: (c: string) => void; width?: string | number; align?: 'left' | 'right' | 'center'
}) {
  return (
    <th onClick={() => onSort?.(col)} style={{
      padding: '0 12px', height: 36, fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 600, letterSpacing: '0.04em',
      textTransform: 'uppercase', color: T.textMid, background: T.tableHead,
      borderBottom: `1px solid ${T.border}`, whiteSpace: 'nowrap', width,
      cursor: onSort ? 'pointer' : 'default', userSelect: 'none', textAlign: align,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, justifyContent: align === 'right' ? 'flex-end' : 'flex-start' }}>
        {label}
        {onSort && <SortIcon col={col} sortCol={sortCol ?? ''} sortDir={sortDir ?? null} />}
      </div>
    </th>
  )
}

// ─── Table row ────────────────────────────────────────────────────────────────
export function TR({
  children, onClick, selected, actions,
}: {
  children: React.ReactNode; onClick?: () => void; selected?: boolean; actions?: React.ReactNode
}) {
  const [hovered, setHovered] = useState(false)
  return (
    <tr
      onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{
        background: selected ? T.rowSelected : hovered ? T.rowHover : T.surface,
        cursor: onClick ? 'pointer' : 'default', position: 'relative',
      }}
    >
      {children}
      {actions && (
        <td style={{ padding: '0 12px', borderBottom: `1px solid ${T.borderLight}`, width: 120, minWidth: 120, position: 'sticky', right: 0, zIndex: 2, background: selected ? T.rowSelected : hovered ? T.rowHover : T.surface, boxShadow: '-1px 0 0 0 var(--c-dfe1e6)' }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {actions}
          </div>
        </td>
      )}
    </tr>
  )
}

// ─── TD ───────────────────────────────────────────────────────────────────────
export function TD({ children, width, mono, right, muted, nowrap, tooltip }: {
  children: React.ReactNode; width?: string | number; mono?: boolean; right?: boolean; muted?: boolean; nowrap?: boolean; tooltip?: string
}) {
  const tdRef = useRef<HTMLTableCellElement>(null)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [truncated, setTruncated] = useState(false)

  const showTooltip = (e: React.MouseEvent) => {
    if (!tooltip) return
    const el = tdRef.current
    const isTruncated = Boolean(el && el.scrollWidth > el.clientWidth)
    setTruncated(isTruncated)
    setPos(isTruncated ? { x: e.clientX, y: e.clientY } : null)
  }

  return (
    <td
      ref={tdRef}
      style={{
        padding: '0 12px', height: 38, fontSize: `calc(${mono ? 12 : 13}px * var(--font-scale, 1))`,
        fontFamily: mono ? "'Consolas','Menlo','Courier New',monospace" : undefined,
        letterSpacing: mono ? '0.01em' : undefined,
        color: muted ? T.textMid : T.text, borderBottom: `1px solid ${T.borderLight}`,
        whiteSpace: nowrap ? 'nowrap' : undefined, width, textAlign: right ? 'right' : 'left',
        maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
      }}
      onMouseEnter={showTooltip}
      onMouseMove={showTooltip}
      onMouseLeave={() => { setPos(null); setTruncated(false) }}
    >
      {children}
      {truncated && pos && createPortal(
        <span style={{
          position: 'fixed', zIndex: 9999, pointerEvents: 'none',
          left: pos.x + 12, top: pos.y - 32,
          background: T.text, color: '#fff', borderRadius: 3, padding: '5px 9px',
          fontSize: 11, whiteSpace: 'nowrap', boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
        }}>
          {tooltip}
        </span>,
        document.body
      )}
    </td>
  )
}

// ─── Filter toolbar ───────────────────────────────────────────────────────────
export function FilterBar({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '8px 16px', background: T.surface,
      borderBottom: `1px solid ${T.border}`, flexShrink: 0, flexWrap: 'wrap',
    }}>
      {children}
    </div>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Search…', width }: { value: string; onChange: (v: string) => void; placeholder?: string; width?: number }) {
  return (
    <div style={{ position: 'relative', flexShrink: 0 }}>
      <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: T.textMuted, display: 'flex' }}>
        <Ico.Search />
      </span>
      <input
        value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{
          height: 30, width: width ?? 220, padding: '0 8px 0 28px', borderRadius: 3,
          border: `1px solid ${T.border}`, background: T.surface, color: T.text, outline: 'none',
        }}
        onFocus={e => { e.target.style.borderColor = T.primary }}
        onBlur={e => { e.target.style.borderColor = T.border }}
      />
    </div>
  )
}

export function FilterSelect({ value, onChange, options, placeholder }: {
  value: string; onChange: (v: string) => void
  options: { value: string; label: string }[]; placeholder?: string
}) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} style={{
      height: 30, padding: '0 24px 0 8px', borderRadius: 3,
      border: `1px solid ${T.border}`, background: T.surface, color: value ? T.text : T.textMuted,
      outline: 'none', cursor: 'pointer', fontSize: `calc(${12}px * var(--font-scale, 1))`, appearance: 'auto',
    }}>
      {placeholder && <option value="">{placeholder}</option>}
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ─── Page layout ──────────────────────────────────────────────────────────────
export function PageHeader({
  title, subtitle, breadcrumb, actions,
}: {
  title: string; subtitle?: string; breadcrumb?: string[]; actions?: React.ReactNode
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 20px', height: 52, background: T.surface,
      borderBottom: `1px solid ${T.border}`, flexShrink: 0,
    }}>
      <div>
        {breadcrumb && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
            {breadcrumb.map((b, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: i < breadcrumb.length - 1 ? T.primary : T.textMid, cursor: i < breadcrumb.length - 1 ? 'pointer' : 'default' }}>{b}</span>
                {i < breadcrumb.length - 1 && <span style={{ color: T.textMuted, fontSize: `calc(${11}px * var(--font-scale, 1))`}}>/</span>}
              </span>
            ))}
          </div>
        )}
        <h1 style={{ fontSize: `calc(${15}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text, lineHeight: 1.2 }}>{title}</h1>
        {subtitle && <p style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, marginTop: 1 }}>{subtitle}</p>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{actions}</div>}
    </div>
  )
}

// ─── Section panel ────────────────────────────────────────────────────────────
export function Panel({
  title, children, actions, noPad, scrollable,
}: {
  title?: string; children: React.ReactNode; actions?: React.ReactNode; noPad?: boolean; scrollable?: boolean
}) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden', flexShrink: scrollable ? 0 : undefined, minWidth: 0 }}>
      {(title || actions) && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          {title && <span style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text }}>{title}</span>}
          {actions && <div style={{ display: 'flex', gap: 6 }}>{actions}</div>}
        </div>
      )}
      {scrollable ? <div role="region" aria-label={`${title} scroll area`} tabIndex={0} style={{ overflow: 'auto', maxHeight: 280, minHeight: 0 }}>{noPad ? children : <div style={{ padding: 14 }}>{children}</div>}</div> : noPad ? children : <div style={{ padding: 14 }}>{children}</div>}
    </div>
  )
}

// ─── Info row ─────────────────────────────────────────────────────────────────
export function InfoRow({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', borderBottom: `1px solid ${T.borderLight}`, minHeight: 32, alignItems: 'center' }}>
      <div style={{ width: 180, padding: '6px 12px', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid, fontWeight: 500, flexShrink: 0, background: T.tableHead, borderRight: `1px solid ${T.borderLight}` }}>{label}</div>
      <div style={{ padding: '6px 12px', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.text, fontFamily: mono ? "'Consolas','Menlo',monospace" : undefined }}>{value}</div>
    </div>
  )
}

// ─── Modal ────────────────────────────────────────────────────────────────────
export function Modal({ title, children, onClose, width = 480 }: {
  title: string; children: React.ReactNode; onClose: () => void; width?: number
}) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(9,30,66,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={onClose}>
      <div style={{ background: T.surface, borderRadius: 3, width, maxHeight: '90vh', overflow: 'auto', boxShadow: '0 8px 24px rgba(9,30,66,0.25)' }}
        onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: `1px solid ${T.border}` }}>
          <span style={{ fontSize: `calc(${14}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text }}>{title}</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: T.textMid, display: 'flex', padding: 2 }}><Ico.X /></button>
        </div>
        <div style={{ padding: 20 }}>{children}</div>
      </div>
    </div>
  )
}

// ─── Inline alert ─────────────────────────────────────────────────────────────
export function Alert({ type, children }: { type: 'warning' | 'error' | 'info' | 'success'; children: React.ReactNode }) {
  const styles = { warning: ['var(--c-7a4800)', 'var(--c-fff8e6)', 'var(--c-ffd591)'], error: ['var(--c-800f00)', 'var(--c-fff0ee)', 'var(--c-ffb3ad)'], info: ['var(--c-003566)', 'var(--c-e8f4fe)', 'var(--c-80bfff)'], success: ['var(--c-024f2a)', 'var(--c-eafbf1)', 'var(--c-6dd9a8)'] } as Record<string, [string, string, string]>
  const [color, bg, border] = styles[type]
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 3, padding: '10px 14px', display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: `calc(${12}px * var(--font-scale, 1))`, color, lineHeight: 1.5 }}>
      <span style={{ flexShrink: 0, marginTop: 1 }}><Ico.Warning /></span>
      <div>{children}</div>
    </div>
  )
}
