import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import type { Catalog, Project } from './types'
import { api } from './api'
import { AuthBar } from './components/AuthBar'
import { Icon } from './components/Icon'
import { Orb } from './components/Orb'
import { Sidebar } from './components/Sidebar'
import { CommandPalette } from './components/CommandPalette'
import { ProjectsContext, TopbarContext } from './shell'
import { AuthContext, type AuthState } from './auth'
import { parseRoute, routeHash, type Route } from './route'
import { forgetTrees } from './trees'
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

const CRUMBS: Record<string, string> = {
  overview: 'Overview',
  agents: 'Agents',
  call: 'Start a call',
  calls: 'Calls',
  knowledge: 'Knowledge',
  tools: 'Tools',
  analytics: 'Analytics',
}

const TAB_NAMES: Record<string, string> = {
  overview: 'Overview',
  agent: 'Agent',
  workflow: 'Workflow',
  models: 'Models',
  calls: 'Calls',
  developer: 'Developer',
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
  const [projects, setProjects] = useState<Project[]>([])
  const [palette, setPalette] = useState(false)
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  // The project "Start a call" opens: the last one visited, else the demo.
  const [lastProject, setLastProject] = useState('demo')

  const reloadProjects = () => {
    api
      .listProjects()
      .then((r) => setProjects(r.projects))
      .catch(() => setProjects([]))
  }

  useEffect(() => {
    api
      .me()
      .then((r) => setAuth({ authRequired: r.auth_required, owner: r.owner }))
      .catch(() => undefined) // an older backend without /api/auth: stay in the open local mode
    api
      .getCatalog()
      .then(setCatalog)
      .catch(() => setCatalog(null))
    reloadProjects()
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (route.view === 'project') setLastProject(route.pid)
    if (route.view === 'project' || route.view === 'agents') forgetTrees()
  }, [route])

  const project = route.view === 'project' ? projects.find((p) => p.id === route.pid) : undefined

  return (
    <AuthContext.Provider value={auth}>
      <ProjectsContext.Provider value={{ projects, reload: reloadProjects }}>
        <TopbarContext.Provider value={slot}>
          <div className="shell">
            <Sidebar
              route={route}
              projects={projects}
              onSearch={() => setPalette(true)}
              foot={<AuthBar auth={auth} onChange={setAuth} />}
            />

            <div className="main">
              <header className="topbar">
                <nav className="topbar__crumbs" aria-label="Breadcrumb">
                  {route.view === 'project' ? (
                    <>
                      <a href="#/agents">Agents</a>
                      <Icon name="chevron" />
                      <a href={`#/agents/${encodeURIComponent(route.pid)}/agent`} className="topbar__agent">
                        <Orb seed={route.pid} size={16} />
                        {project?.name ?? route.pid}
                      </a>
                      <Icon name="chevron" />
                      <span>{TAB_NAMES[route.tab]}</span>
                    </>
                  ) : (
                    <span>{CRUMBS[route.view]}</span>
                  )}
                </nav>
                <div className="topbar__actions">
                  <div className="topbar__slot" ref={setSlot} />
                  <a
                    className="btn-secondary topbar__docs"
                    href="https://github.com/MattBi-web/voice-orchestrator"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Docs
                  </a>
                </div>
              </header>

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
                      projects={projects}
                      go={(view) =>
                        go(
                          view === 'call'
                            ? { view: 'call', pid: 'demo' }
                            : view === 'agents'
                              ? { view: 'project', pid: 'demo', tab: 'agent' }
                              : { view },
                        )
                      }
                    />
                  )}

                  {route.view === 'agents' && (
                    <ProjectsList
                      catalog={catalog}
                      creating={Boolean(route.create)}
                      onCloseCreate={() => go({ view: 'agents' })}
                      onOpen={(pid) => {
                        reloadProjects()
                        go({ view: 'project', pid, tab: 'agent' })
                      }}
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
                      onBack={() => {
                        reloadProjects()
                        go({ view: 'agents' })
                      }}
                      onChanged={reloadProjects}
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
          </div>
          <CommandPalette open={palette} onClose={() => setPalette(false)} projects={projects} />
        </TopbarContext.Provider>
      </ProjectsContext.Provider>
    </AuthContext.Provider>
  )
}

function CallsPage({ initial }: { initial: string | null }) {
  const [selected, setSelected] = useState<string | null>(initial)
  return <Conversations selectedCallId={selected} onSelectCall={setSelected} />
}

export default App
