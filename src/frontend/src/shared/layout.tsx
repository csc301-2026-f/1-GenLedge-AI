import React, { useState } from 'react'
import type { Screen, Nav } from '../app/types'
import { T, Ico } from './ui'

// ─── Nav config ───────────────────────────────────────────────────────────────
export const NAV_SECTIONS = [
  {
    label: 'CONNECTOR',
    items: [
      { id: 'sources' as Screen, label: 'Data Sources', Icon: Ico.Database },
      { id: 'discover' as Screen, label: 'Schema Discovery', Icon: Ico.Search },
      { id: 'route' as Screen, label: 'AI Routing', Icon: Ico.Sparkle },
      { id: 'mapping' as Screen, label: 'Mapping Studio', Icon: Ico.Map },
      { id: 'run' as Screen, label: 'Transform & Load', Icon: Ico.Play },
    ],
  },
  {
    label: 'OPERATIONS',
    items: [
      { id: 'monitor' as Screen, label: 'Pipelines & Monitor', Icon: Ico.Clock },
    ],
  },
]

// ─── Global top bar ───────────────────────────────────────────────────────────
export function TopBar({ user, onLogout, loggingOut, logoutError }: { user: { email: string; role: string }; onLogout: () => void; loggingOut: boolean; logoutError: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{
      height: 44, background: T.sidebar, display: 'flex', alignItems: 'center',
      flexShrink: 0, zIndex: 20,
    }}>
      {/* Logo zone */}
      <div style={{ width: 220, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', borderRight: `1px solid ${T.sidebarBorder}` }}>
        <div style={{ width: 24, height: 24, background: T.primary, borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 700, color: '#fff', flexShrink: 0 }}>GL</div>
        <span style={{ color: '#E2E8F0', fontWeight: 600, fontSize: `calc(${13}px * var(--font-scale, 1))`}}>GenLedge Connector</span>
      </div>
      {/* Center — global search (decorative for prototype) */}
      <div style={{ flex: 1, padding: '0 20px' }}>
        <div style={{ maxWidth: 360, position: 'relative' }}>
          <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.4)', display: 'flex' }}><Ico.Search /></span>
          <input placeholder="Search records, pipelines, sources…"
            style={{ height: 30, width: '100%', paddingLeft: 28, paddingRight: 8, borderRadius: 3, border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.08)', color: '#E2E8F0', outline: 'none', fontSize: `calc(${12}px * var(--font-scale, 1))`}} />
        </div>
      </div>
      {/* Right controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 16px' }}>
        <button style={{ width: 32, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', borderRadius: 3 }}><Ico.Help /></button>
        <button style={{ width: 32, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', borderRadius: 3 }}><Ico.Bell /></button>
        <div style={{ position: 'relative' }}>
          <button onClick={() => setOpen(o => !o)} style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '4px 8px', border: 'none', background: 'transparent', cursor: 'pointer', borderRadius: 3 }}>
            <div style={{ width: 26, height: 26, borderRadius: '50%', background: T.primary, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 700, color: '#fff' }}>
              {user.email.charAt(0).toUpperCase()}
            </div>
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: '#E2E8F0', fontWeight: 500 }}>{user.email.split('@')[0]}</div>
              <div style={{ fontSize: `calc(${10}px * var(--font-scale, 1))`, color: 'rgba(255,255,255,0.5)', textTransform: 'capitalize' }}>{user.role}</div>
            </div>
            <Ico.ChevronD />
          </button>
          {open && (
            <div style={{ position: 'absolute', right: 0, top: '100%', background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, minWidth: 180, boxShadow: '0 4px 12px rgba(0,0,0,0.15)', zIndex: 50 }}>
              <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
                <div style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: 600 }}>{user.email}</div>
                <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, textTransform: 'capitalize', marginTop: 2 }}>{user.role}</div>
              </div>
              <button disabled={loggingOut} onClick={onLogout} style={{ width: '100%', padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.text, textAlign: 'left' }}
                onMouseEnter={e => (e.currentTarget.style.background = T.rowHover)}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}>
                <Ico.LogOut /> {loggingOut ? 'Signing Out…' : 'Sign Out'}
              </button>
              {logoutError && <div role="alert" style={{ padding: '8px 14px', color: 'var(--c-b42318)', fontSize: 12 }}>{logoutError} Use Sign Out to retry.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
export function Sidebar({ current, onNav, completedThrough }: { current: Screen; onNav: Nav; completedThrough: number }) {
  const ALL_STEPS: Screen[] = ['sources', 'discover', 'route', 'mapping', 'run', 'monitor']

  return (
    <nav style={{ width: 220, background: T.sidebar, display: 'flex', flexDirection: 'column', flexShrink: 0, borderRight: `1px solid ${T.sidebarBorder}`, overflow: 'auto' }}>
      {NAV_SECTIONS.map(section => (
        <div key={section.label} style={{ marginTop: 20 }}>
          <div style={{ padding: '0 12px 6px', fontSize: `calc(${10}px * var(--font-scale, 1))`, fontWeight: 700, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.35)' }}>{section.label}</div>
          {section.items.map(item => {
            const isActive = current === item.id
            const idx = ALL_STEPS.indexOf(item.id)
            const isWorkflowStep = section.label === 'CONNECTOR'
            const done = isWorkflowStep && idx >= 0 && idx <= completedThrough
            const locked = isWorkflowStep && idx > completedThrough + 1
            return (
              <button key={item.id} onClick={() => !locked && onNav(item.id)} disabled={locked} aria-current={isWorkflowStep && isActive ? 'step' : undefined} aria-label={isWorkflowStep ? `${item.label}${done ? ', completed' : locked ? ', locked' : ', current step'}` : item.label} style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 9,
                padding: '0 12px', height: 34, border: 'none', cursor: locked ? 'not-allowed' : 'pointer', textAlign: 'left',
                background: isActive ? 'rgba(1,118,211,0.22)' : 'transparent',
                borderLeft: isActive ? `3px solid ${T.sidebarActiveBorder}` : '3px solid transparent',
                color: locked ? 'rgba(176,190,197,0.45)' : isActive ? '#E2E8F0' : T.sidebarText,
                transition: 'background 0.12s',
              }}
                onMouseEnter={e => { if (!isActive && !locked) e.currentTarget.style.background = 'rgba(255,255,255,0.07)' }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ opacity: locked ? 0.45 : isActive ? 1 : 0.7, width: 13, display: 'flex', justifyContent: 'center' }}>
                  {isWorkflowStep && done ? <Ico.Check /> : isWorkflowStep && locked ? <Ico.Lock /> : <item.Icon />}
                </span>
                <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, fontWeight: isActive ? 600 : 400, flex: 1 }}>{item.label}</span>
                {isWorkflowStep && <span style={{ fontSize: `calc(${10}px * var(--font-scale, 1))`, color: done ? '#86E1AE' : locked ? 'rgba(176,190,197,0.36)' : isActive ? '#B9DBF7' : 'transparent' }}>{done ? 'Done' : locked ? 'Locked' : 'Current'}</span>}
              </button>
            )
          })}
        </div>
      ))}

      <div style={{ marginTop: 24, borderTop: `1px solid ${T.sidebarBorder}`, padding: '12px 12px 0' }}>
        <div style={{ fontSize: `calc(${10}px * var(--font-scale, 1))`, fontWeight: 700, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.35)', marginBottom: 4 }}>ADMIN</div>
        {[{ label: 'User Management', Icon: Ico.Users }, { label: 'Display Settings', Icon: Ico.Settings }].map(item => (
          <button key={item.label} onClick={() => { if (item.label === 'Display Settings') window.dispatchEvent(new Event('genledge-open-display')) }} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 9, padding: '0 12px', height: 34, border: 'none', cursor: 'pointer', background: 'transparent', color: T.sidebarText }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.07)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <span style={{ opacity: 0.7 }}><item.Icon /></span>
            <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`}}>{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
