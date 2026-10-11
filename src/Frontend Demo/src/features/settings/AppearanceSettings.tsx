import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

// Display preferences are local to this browser and apply across every screen.
type DisplayPreferences = { scale: number; font: number; theme: 'light' | 'dark' }
const displayDefaults: DisplayPreferences = { scale: 1.1, font: 1, theme: 'light' }
export function AppearanceSettings() {
  const [prefs, setPrefs] = useState<DisplayPreferences>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('genledge-display') || '{}')
      return {
        scale: [0.9, 1, 1.1, 1.2, 1.3].includes(saved.scale) ? saved.scale : 1.1,
        font: [0.9, 1, 1.1, 1.2].includes(saved.font) ? saved.font : 1,
        theme: saved.theme === 'dark' ? 'dark' : 'light',
      }
    } catch { return displayDefaults }
  })
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener('genledge-open-display', show)
    return () => window.removeEventListener('genledge-open-display', show)
  }, [])
  useEffect(() => {
    document.documentElement.style.setProperty('--ui-scale', String(prefs.scale))
    document.documentElement.style.setProperty('--font-scale', String(prefs.font))
    document.documentElement.dataset.theme = prefs.theme
    try { localStorage.setItem('genledge-display', JSON.stringify(prefs)) } catch { /* Storage may be unavailable in embedded previews. */ }
  }, [prefs])
  useEffect(() => {
    if (open) dialog.current?.showModal()
    else if (dialog.current?.open) dialog.current.close()
  }, [open])
  return createPortal(<>
    <dialog ref={dialog} className="appearance-dialog" aria-labelledby="appearance-title" onCancel={() => setOpen(false)} onClose={() => { setOpen(false); trigger.current?.focus() }} onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}>
      <section className="appearance-content">
        <header><div><h2 id="appearance-title">Display settings</h2><p>Make GenLedge comfortable for you.</p></div><button type="button" aria-label="Close display settings" onClick={() => setOpen(false)}>×</button></header>
        <label htmlFor="display-scale">UI size <span>{Math.round(prefs.scale * 100)}%</span></label>
        <select id="display-scale" value={prefs.scale} onChange={e => setPrefs(p => ({ ...p, scale: Number(e.target.value) }))}>
          {[0.9, 1, 1.1, 1.2, 1.3].map(v => <option key={v} value={v}>{Math.round(v * 100)}%{v === 1.1 ? ' (default)' : ''}</option>)}
        </select>
        <p className="appearance-hint">Scales controls, spacing and text together.</p>
        <label htmlFor="display-font">Font size</label>
        <select id="display-font" value={prefs.font} onChange={e => setPrefs(p => ({ ...p, font: Number(e.target.value) }))}>
          <option value="0.9">Small · 90%</option><option value="1">Standard · 100%</option><option value="1.1">Large · 110%</option><option value="1.2">Extra large · 120%</option>
        </select>
        <p className="appearance-hint">Adjusts text independently of UI size.</p>
        <label htmlFor="display-theme">Color mode</label>
        <select id="display-theme" value={prefs.theme} onChange={e => setPrefs(p => ({ ...p, theme: e.target.value as 'light' | 'dark' }))}>
          <option value="light">Light</option><option value="dark">Dark</option>
        </select>
        <div className="appearance-sample" style={{ fontSize: 14 * prefs.font }}>Aa — The quick brown fox<br /><small>Preview of your text size</small></div>
        <p className="appearance-hint">Changes apply immediately and are saved on this browser.</p>
        <footer><button type="button" onClick={() => setPrefs({ ...displayDefaults })}>Reset defaults</button><button type="button" className="appearance-done" onClick={() => setOpen(false)}>Done</button></footer>
      </section>
    </dialog>
  </>, document.body)
}
