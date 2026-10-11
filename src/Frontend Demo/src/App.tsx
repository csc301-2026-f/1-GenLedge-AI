import { useState } from 'react'
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
  const [user, setUser] = useState<{ email: string; role: string } | null>(null)
  const [completedThrough, setCompletedThrough] = useState(-1)
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

  if (screen === 'login' || !user) {
    return <><LoginScreen onLogin={u => { setUser(u); setCompletedThrough(-1); setScreen('sources') }} /><AppearanceSettings /></>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <AppearanceSettings />
      <TopBar user={user} onLogout={() => { setUser(null); setCompletedThrough(-1); setScreen('login') }} />
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
