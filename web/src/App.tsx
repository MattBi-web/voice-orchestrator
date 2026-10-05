import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import type { Catalog } from './types'
import { api } from './api'
import { AuthBar } from './components/AuthBar'
import { Icon, type IconName } from './components/Icon'
import { AuthContext, type AuthState } from './auth'
import { parseRoute, routeHash, type Route } from './route'
import { forgetTrees, useProjects } from './trees'
import './App.css'

// D9: everything loads on demand. The two heavy dependencies sit behind
// these — livekit-client (call) and recharts (analytics) — so the first
// page load doesn't pay for them.
const ProjectsList = lazy(() => import('./components/ProjectsList').then((m) => ({ default: m.ProjectsList })))
const ProjectPage = lazy(() => import('./components/ProjectPage').then((m) => ({ default: m.ProjectPage })))
const VoiceTestConsole = lazy(() => import('./components/VoiceTestConsole').then((m) => ({ default: m.VoiceTestConsole })))
const Dashboard = lazy(() => import('./components/Dashboard').then((m) => ({ default: m.Dashboard })))
const Conversations = lazy(() => import('./components/Conversations').then((m) => ({ default: m.Conversations })))
const KnowledgeBase = lazy(() => import('./components/KnowledgeBase').then((m) => ({ default: m.KnowledgeBase })))
const Overview = lazy(() => import('./components/Overview').then((m) => ({ default: m.Overview })))
const ToolsPage = lazy(() => import('./components/ToolsPage').then((m) => ({ default: m.ToolsPage })))

type NavView = 'overview' | 'agents' | 'knowledge' | 'tools' | 'calls' | 'analytics'

const NAV: { view: NavView; label: string; icon: IconName }[] = [
  { view: 'overview', label: 'Overview', icon: 'home' },
  { view: 'agents', label: 'Agents', icon: 'agents' },
  { view: 'knowledge', label: 'Knowledge', icon: 'book' },
  { view: 'tools', label: 'Tools', icon: 'plug' },
  { view: 'calls', label: 'Calls', icon: 'list' },
  { view: 'analytics', label: 'Analytics', icon: 'chart' },
]

const PAGES: Record<'knowledge' | 'tools' | 'call' | 'calls' | 'analytics', { title: string; lede: string }> = {
  knowledge: {
    title: 'Knowledge',
    lede: 'Documents agents answer from. Add text, a file or a web page, and check which passages a question retrieves.',
  },
  tools: {
    title: 'Tools',
    lede: 'Actions agents can take mid-call: built-in ones, HTTP webhooks and MCP servers. Any agent can use them.',
  },
  call: {
    title: 'Start a call',
    lede: 'Talk to an agent from your browser and watch each turn: who answered, which router level decided, which tools ran.',
  },
  calls: {
    title: 'Calls',
    lede: 'Every call turn by turn: which agent answered, which router level decided it, which tools ran.',
  },
  analytics: {
    title: 'Analytics',
    lede: 'Call volume, how the router resolves turns, tool usage and evaluation results.',
  },
}

function PageHead({ page, actions }: { page: keyof typeof PAGES; actions?: ReactNode }) {
  const p = PAGES[page]
  return (
    <header className="page__head">
      <div>
        <h1>{p.title}</h1>
        <p className="page__lede">{p.lede}</p>
      </div>
      {actions && <div className="page__actions">{actions}</div>}
    </header>
  )
}

function BrandMark() {
  // One line in, three routes out — colored by router level.
  return (
    <svg className="nav__mark" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
      <path d="M3 12h6" stroke="var(--ink)" />
      <path d="M9 12c3 0 4-6 8-6h4" stroke="var(--gate)" />
      <path d="M9 12h12" stroke="var(--pattern)" />
      <path d="M9 12c3 0 4 6 8 6h4" stroke="var(--llm)" />
      <circle cx="9" cy="12" r="2" fill="var(--ink)" stroke="none" />
    </svg>
  )
}

function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute(window.location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const go = (r: Route) => {
    const hash = routeHash(r)
    if (hash === window.location.hash) setRoute(r)
    else window.location.hash = hash
  }
  return [route, go]
}

function App() {
  const [route, go] = useRoute()
  const [auth, setAuth] = useState<AuthState>({ authRequired: false, owner: true })
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  // The project "Start a call" opens: the last one visited, else the demo.
  const [lastProject, setLastProject] = useState('demo')
  const projects = useProjects()

  useEffect(() => {
    api
      .me()
      .then((r) => setAuth({ authRequired: r.auth_required, owner: r.owner }))
      .catch(() => undefined) // an older backend without /api/auth: stay in the open local mode
    api
      .getCatalog()
      .then(setCatalog)
      .catch(() => setCatalog(null))
  }, [])

  useEffect(() => {
    if (route.view === 'project') setLastProject(route.pid)
    if (route.view === 'project' || route.view === 'agents') forgetTrees()
  }, [route])

  const navActive: NavView | 'call' = route.view === 'project' ? 'agents' : route.view

  return (
    <AuthContext.Provider value={auth}>
      <div className="shell">
        <nav className="nav" aria-label="Main">
          <a className="nav__brand" href="#/">
            <BrandMark />
            Voice Orchestrator
          </a>
          <a
            className="btn-primary nav__call"
            href={`#/call/${encodeURIComponent(lastProject)}`}
            aria-current={navActive === 'call' ? 'page' : undefined}
          >
            <Icon name="phone" />
            Start a call
          </a>
          {NAV.map((item) => (
            <a
              key={item.view}
              className="nav__link"
              href={item.view === 'overview' ? '#/' : `#/${item.view}`}
              aria-current={navActive === item.view ? 'page' : undefined}
            >
              <Icon name={item.icon} />
              {item.label}
            </a>
          ))}
          <div className="nav__foot">
            <AuthBar auth={auth} onChange={setAuth} />
          </div>
        </nav>

        <div className={route.view === 'project' ? 'page page--wide' : 'page'}>
          {auth.authRequired && !auth.owner && (
            <p className="app__readonly">
              You’re viewing a read-only demo. Explore the agents, call them, and try the text test. Sign in to make
              changes.
            </p>
          )}

          <Suspense fallback={<p className="app__hint">Loading…</p>}>
            {route.view === 'overview' && (
              <Overview
                go={(view) => go(view === 'call' ? { view: 'call', pid: 'demo' } : view === 'agents' ? { view: 'project', pid: 'demo', tab: 'build' } : { view })}
              />
            )}

            {route.view === 'agents' && (
              <ProjectsList
                catalog={catalog}
                onOpen={(pid) => go({ view: 'project', pid, tab: 'build' })}
                onCall={(pid) => go({ view: 'call', pid })}
              />
            )}

            {route.view === 'project' && (
              <ProjectPage
                key={route.pid}
                pid={route.pid}
                tab={route.tab}
                agentId={route.agent}
                catalog={catalog}
                go={(tab, agent) => go({ view: 'project', pid: route.pid, tab, agent })}
                onCall={() => go({ view: 'call', pid: route.pid })}
                onBack={() => go({ view: 'agents' })}
              />
            )}

            {route.view === 'call' && (
              <>
                <PageHead page="call" />
                <VoiceTestConsole
                  key={route.pid ?? lastProject}
                  pid={route.pid ?? lastProject}
                  projects={projects}
                  onPickProject={(pid) => go({ view: 'call', pid })}
                />
              </>
            )}

            {route.view === 'knowledge' && (
              <>
                <PageHead page="knowledge" />
                <KnowledgeBase />
              </>
            )}
            {route.view === 'tools' && (
              <>
                <PageHead page="tools" />
                <ToolsPage onChanged={() => undefined} />
              </>
            )}
            {route.view === 'calls' && (
              <>
                <PageHead page="calls" />
                <CallsPage key={route.call ?? ''} initial={route.call ?? null} />
              </>
            )}
            {route.view === 'analytics' && (
              <>
                <PageHead page="analytics" />
                <Dashboard onOpenCall={(call) => go({ view: 'calls', call })} />
              </>
            )}
          </Suspense>
        </div>
      </div>
    </AuthContext.Provider>
  )
}

function CallsPage({ initial }: { initial: string | null }) {
  const [selected, setSelected] = useState<string | null>(initial)
  return <Conversations selectedCallId={selected} onSelectCall={setSelected} />
}

export default App
