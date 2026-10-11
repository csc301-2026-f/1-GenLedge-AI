import { useEffect, useRef, useState } from 'react'
import { currentUser, logout, type AuthUser } from './features/auth/client'
import type { Screen, Nav } from './app/types'
import { TopBar, Sidebar } from './shared'
import { LoginScreen } from './features/auth/LoginScreen'
import { SourcesScreen } from './features/sources/SourcesScreen'
import { DiscoverScreen } from './features/discovery/DiscoverScreen'
import { RouteScreen } from './features/mappings/RouteScreen'
import { MappingScreen } from './features/mappings/MappingScreen'
import { RunScreen } from './features/runs/RunScreen'
import { MonitorScreen } from './features/runs/MonitorScreen'
import { AppearanceSettings } from './features/settings/AppearanceSettings'

// ─── Root ─────────────────────────────────────────────────────────────────────
export default function App() {
  const [screen, setScreen] = useState<Screen>('login')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [completedThrough, setCompletedThrough] = useState(-1)
  const [checking, setChecking] = useState(true)
  const [connectionError, setConnectionError] = useState('')
  const [restoreAttempt, setRestoreAttempt] = useState(0)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const restoreRequest = useRef<Promise<AuthUser | null> | null>(null)
  const signingOut = useRef(false)

  const signedIn = (nextUser: AuthUser) => {
    setUser(nextUser)
    setConnectionError('')
    setCompletedThrough(-1)
    setScreen('sources')
  }

  useEffect(() => {
    let active = true
    setChecking(true)
    setConnectionError('')
    // Strict Mode repeats effect setup; both setups observe the same request.
    const request = restoreRequest.current ??= currentUser()
    request.then(nextUser => {
      if (!active) return
      if (nextUser) signedIn(nextUser)
      else { setUser(null); setScreen('login'); setCompletedThrough(-1) }
    }).catch((error: unknown) => {
      if (active) {
        setUser(null)
        setConnectionError(error instanceof Error ? error.message : 'Unable to restore session. Please try again.')
      }
    }).finally(() => { if (active) setChecking(false) })
    return () => { active = false }
  }, [restoreAttempt])

  const signOut = async () => {
    if (signingOut.current) return
    signingOut.current = true
    setLoggingOut(true); setLogoutError('')
    try {
      await logout()
      setUser(null); setCompletedThrough(-1); setScreen('login')
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Unable to sign out. Please try again.')
    } finally {
      signingOut.current = false
      setLoggingOut(false)
    }
  }

  const workflow: Screen[] = ['sources', 'discover', 'route', 'mapping', 'run']
  const navigateWorkflow: Nav = next => {
    if (next === 'monitor') { setScreen(next); return }
    const nextIndex = workflow.indexOf(next)
    if (nextIndex <= completedThrough + 1) setScreen(next)
  }
  const advance = (from: Screen, next: Screen) => {
    const fromIndex = workflow.indexOf(from)
    setCompletedThrough(fromIndex)
    setScreen(next)
  }
  const invalidateAfter = (step: Screen) => {
    const stepIndex = workflow.indexOf(step)
    setCompletedThrough(done => Math.min(done, stepIndex))
  }

  if (checking) return <div role="status" style={{ padding: 24 }}>Checking session…</div>

  if (screen === 'login' || !user) {
    return <><LoginScreen onLogin={signedIn} connectionError={connectionError} onRetry={() => { restoreRequest.current = null; setRestoreAttempt(n => n + 1) }} /><AppearanceSettings /></>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <AppearanceSettings />
      <TopBar user={user} onLogout={signOut} loggingOut={loggingOut} logoutError={logoutError} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar current={screen} onNav={navigateWorkflow} completedThrough={completedThrough} />
        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {screen === 'sources'  && <SourcesScreen  onNav={navigateWorkflow} onAdvance={() => advance('sources', 'discover')} onInvalidate={() => invalidateAfter('sources')} />}
          {screen === 'discover' && <DiscoverScreen onNav={navigateWorkflow} onAdvance={() => advance('discover', 'route')} onInvalidate={() => invalidateAfter('discover')} />}
          {screen === 'route'    && <RouteScreen    onNav={navigateWorkflow} onAdvance={() => advance('route', 'mapping')} onInvalidate={() => invalidateAfter('route')} />}
          {screen === 'mapping'  && <MappingScreen  onNav={navigateWorkflow} onAdvance={() => advance('mapping', 'run')} onInvalidate={() => invalidateAfter('mapping')} />}
          {screen === 'run'      && <RunScreen      onNav={navigateWorkflow} onAdvance={() => advance('run', 'monitor')} onInvalidate={() => invalidateAfter('run')} />}
          {screen === 'monitor'  && <MonitorScreen  onNav={navigateWorkflow} />}
        </main>
      </div>
    </div>
  )
}
