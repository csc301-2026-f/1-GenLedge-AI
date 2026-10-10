import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert } from '../../shared'
import type { Screen, Nav } from '../../app/types'
import { login, type AuthUser } from './api'

// ─── US1 — Login ──────────────────────────────────────────────────────────────
export function LoginScreen({ onLogin }: { onLogin: (u: AuthUser) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    if (loading) return
    if (!email.trim()) { setError('Email is required.'); return }
    if (!password) { setError('Password is required.'); return }
    setLoading(true); setError('')
    try {
      const user = await login(email, password, rememberMe)
      setPassword('')
      onLogin(user)
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to sign in. Please retry.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--c-eef2f6)' }}>
      {/* Top bar */}
      <div style={{ height: 44, background: T.sidebar, display: 'flex', alignItems: 'center', padding: '0 24px', gap: 10 }}>
        <div style={{ width: 24, height: 24, background: T.primary, borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 700, color: '#fff' }}>GL</div>
        <span style={{ color: '#E2E8F0', fontWeight: 600, fontSize: `calc(${13}px * var(--font-scale, 1))`}}>GenLedge Connector</span>
      </div>

      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 380 }}>
          <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ background: T.tableHead, borderBottom: `1px solid ${T.border}`, padding: '16px 24px' }}>
              <h1 style={{ fontSize: `calc(${15}px * var(--font-scale, 1))`, fontWeight: 600, color: T.text }}>Sign In</h1>
              <p style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid, marginTop: 3 }}>Use your organization credentials to access GenLedge.</p>
            </div>
            <form onSubmit={e => { e.preventDefault(); void submit() }} style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
              <TextInput label="Email Address" type="email" value={email} onChange={setEmail} placeholder="name@company.com" />
              <TextInput label="Password" type="password" value={password} onChange={setPassword} placeholder="••••••••" />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none' }}>
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={e => setRememberMe(e.target.checked)}
                    style={{ width: 14, height: 14, accentColor: T.primary, cursor: 'pointer', flexShrink: 0 }}
                  />
                  <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>Remember me</span>
                </label>
                <span style={{ position: 'relative', display: 'inline-block' }}
                  onMouseEnter={e => { const t = e.currentTarget.querySelector('.it-tip') as HTMLElement; if (t) t.style.opacity = '1' }}
                  onMouseLeave={e => { const t = e.currentTarget.querySelector('.it-tip') as HTMLElement; if (t) t.style.opacity = '0' }}
                >
                  <span style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid, textDecoration: 'underline', cursor: 'default' }}>
                    Having trouble logging in?
                  </span>
                  <span className="it-tip" style={{
                    position: 'absolute', bottom: '100%', right: 0, marginBottom: 6,
                    background: T.text, color: '#fff', borderRadius: 3, padding: '5px 9px',
                    fontSize: `calc(${11}px * var(--font-scale, 1))`, whiteSpace: 'nowrap',
                    pointerEvents: 'none', opacity: 0, transition: 'opacity 0s',
                  }}>
                    Contact System IT for help
                  </span>
                </span>
              </div>
              {error && <div style={{ fontSize: `calc(${12}px * var(--font-scale, 1))`, color: 'var(--c-b42318)', background: 'var(--c-fef3f2)', border: '1px solid var(--c-fecdca)', padding: '8px 12px', borderRadius: 3 }}>{error}</div>}
              <Btn type="submit" variant="primary" disabled={loading} className="w-full justify-center" >
                {loading
                  ? <><span style={{ width: 12, height: 12, border: '2px solid #fff', borderTopColor: 'transparent', borderRadius: '50%' }} className="spin" />Authenticating…</>
                  : 'Sign In'}
              </Btn>
              {rememberMe && (
                <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12, fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted }}>
                  Session will persist for 14 days. Uncheck "Remember me" to use a session-only login.
                </div>
              )}
            </form>
          </div>
          <div style={{ textAlign: 'center', marginTop: 16, fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted }}>GenLedge Connector v2.4.1 · ACME Corp Internal Systems</div>
        </div>
      </div>
    </div>
  )
}
