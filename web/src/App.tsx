import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import type { Agent } from './types'
import { api, ApiError } from './api'
import { findAgent } from './tree'
import { Tree } from './components/Tree'
import { AgentForm } from './components/AgentForm'
import { TestBox } from './components/TestBox'
import { AuthBar } from './components/AuthBar'
import { Icon, type IconName } from './components/Icon'
import { AuthContext, type AuthState } from './auth'
import './App.css'

// D9: everything except the agents view loads on demand. The two heavy
// dependencies sit behind these — livekit-client (call) and recharts
// (analytics) — so the first page load doesn't pay for them.
const AgentGraph = lazy(() => import('./components/AgentGraph').then((m) => ({ default: m.AgentGraph })))
const VoiceTestConsole = lazy(() => import('./components/VoiceTestConsole').then((m) => ({ default: m.VoiceTestConsole })))
const Dashboard = lazy(() => import('./components/Dashboard').then((m) => ({ default: m.Dashboard })))
const Conversations = lazy(() => import('./components/Conversations').then((m) => ({ default: m.Conversations })))
const KnowledgeBase = lazy(() => import('./components/KnowledgeBase').then((m) => ({ default: m.KnowledgeBase })))
const Overview = lazy(() => import('./components/Overview').then((m) => ({ default: m.Overview })))
const ToolsPage = lazy(() => import('./components/ToolsPage').then((m) => ({ default: m.ToolsPage })))

type Selection = { kind: 'none' } | { kind: 'edit'; agentId: string } | { kind: 'create'; parentId: string }

type View = 'overview' | 'agents' | 'knowledge' | 'tools' | 'call' | 'calls' | 'analytics'
type AgentsSubview = 'tree' | 'graph'

const NAV: { view: View; label: string; icon: IconName }[] = [
  { view: 'overview', label: 'Overview', icon: 'home' },
  { view: 'agents', label: 'Agents', icon: 'agents' },
  { view: 'knowledge', label: 'Knowledge', icon: 'book' },
  { view: 'tools', label: 'Tools', icon: 'plug' },
  { view: 'calls', label: 'Calls', icon: 'list' },
  { view: 'analytics', label: 'Analytics', icon: 'chart' },
]

const PAGES: Record<Exclude<View, 'overview'>, { title: string; lede: string }> = {
  agents: {
    title: 'Agents',
    lede:
      'One phone line, a family of specialists. A three-level router — gate, pattern, LLM fallback — decides which agent answers each turn.',
  },
  knowledge: {
    title: 'Knowledge',
    lede: 'Documents agents answer from. Add text, a file or a web page, and check which passages a question retrieves.',
  },
  tools: {
    title: 'Tools',
    lede: 'Actions agents can take mid-call: built-in ones, HTTP webhooks and MCP servers.',
  },
  call: {
    title: 'Start a call',
    lede: 'Talk to the agent family from your browser. The receptionist answers and hands you over to a specialist.',
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

function PageHead({ view, actions }: { view: Exclude<View, 'overview'>; actions?: ReactNode }) {
  const page = PAGES[view]
  return (
    <header className="page__head">
      <div>
        <h1>{page.title}</h1>
        <p className="page__lede">{page.lede}</p>
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

function App() {
  const [view, setView] = useState<View>('overview')
  const [agentsSubview, setAgentsSubview] = useState<AgentsSubview>('tree')
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null)
  const [root, setRoot] = useState<Agent | null>(null)
  const [tools, setTools] = useState<string[]>([])
  const [selection, setSelection] = useState<Selection>({ kind: 'none' })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState<string | null>(null)
  const [auth, setAuth] = useState<AuthState>({ authRequired: false, owner: true })

  useEffect(() => {
    api
      .me()
      .then((r) => setAuth({ authRequired: r.auth_required, owner: r.owner }))
      .catch(() => undefined) // an older backend without /api/auth: stay in the open local mode
  }, [])

  const reload = async () => {
    try {
      const [tree, toolList] = await Promise.all([api.getTree(), api.listTools()])
      setRoot(tree.root)
      setTools(toolList.tools)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const handleSaved = () => {
    setSelection({ kind: 'none' })
    reload()
  }

  const handleExport = async () => {
    if (
      !confirm(
        'Overwrite config/agents.yaml with the current family? The CLI reads that file. It is tracked by git: ' +
          'uncommitted changes in it will be lost.',
      )
    ) {
      return
    }
    setExporting(true)
    setExportResult(null)
    setError(null)
    try {
      const result = await api.exportAgents()
      setExportResult(`Exported ${result.agent_count} agents to agents.yaml.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setExporting(false)
    }
  }

  const selectedAgent = selection.kind === 'edit' ? findAgent(root, selection.agentId) : undefined
  const parentAgent = selection.kind === 'create' ? findAgent(root, selection.parentId) : undefined

  const go = (next: View) => {
    setView(next)
    window.scrollTo({ top: 0 })
  }

  const agentsActions = (
    <>
      <div className="app__subtabs" role="tablist" aria-label="Agents view">
        {(['tree', 'graph'] as AgentsSubview[]).map((v) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={agentsSubview === v}
            className={agentsSubview === v ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setAgentsSubview(v)}
          >
            {v === 'tree' ? 'List' : 'Graph'}
          </button>
        ))}
      </div>
      {auth.owner && (
        <div className="app__export">
          {exportResult && <span className="app__export-result">{exportResult}</span>}
          <button type="button" className="btn-secondary" onClick={handleExport} disabled={exporting}>
            {exporting ? 'Exporting…' : 'Export YAML'}
          </button>
        </div>
      )}
    </>
  )

  return (
    <AuthContext.Provider value={auth}>
      <div className="shell">
        <nav className="nav" aria-label="Main">
          <button type="button" className="nav__brand" onClick={() => go('overview')}>
            <BrandMark />
            Voice Orchestrator
          </button>
          <button
            type="button"
            className="btn-primary nav__call"
            aria-current={view === 'call' ? 'page' : undefined}
            onClick={() => go('call')}
          >
            <Icon name="phone" />
            Start a call
          </button>
          {NAV.map((item) => (
            <button
              key={item.view}
              type="button"
              className="nav__link"
              aria-current={view === item.view ? 'page' : undefined}
              onClick={() => go(item.view)}
            >
              <Icon name={item.icon} />
              {item.label}
            </button>
          ))}
          <div className="nav__foot">
            <AuthBar auth={auth} onChange={setAuth} />
          </div>
        </nav>

        <div className="page">
          {auth.authRequired && !auth.owner && (
            <p className="app__readonly">
              You're viewing a read-only demo. Explore the agents, start a call, and try the text test. Sign in to make
              changes.
            </p>
          )}
          {error && <p className="error app__error">{error}</p>}

          {view !== 'overview' && <PageHead view={view} actions={view === 'agents' ? agentsActions : undefined} />}

          <Suspense fallback={<p className="app__hint">Loading…</p>}>
            {view === 'overview' ? (
              <Overview root={root} go={go} />
            ) : view === 'knowledge' ? (
              <KnowledgeBase root={root} />
            ) : view === 'tools' ? (
              <ToolsPage onChanged={reload} />
            ) : view === 'call' ? (
              <VoiceTestConsole />
            ) : view === 'analytics' ? (
              <Dashboard
                onOpenCall={(callId) => {
                  setSelectedCallId(callId)
                  go('calls')
                }}
              />
            ) : view === 'calls' ? (
              <Conversations selectedCallId={selectedCallId} onSelectCall={setSelectedCallId} />
            ) : loading ? (
              <p className="app__hint">Loading…</p>
            ) : (
              <div className={agentsSubview === 'graph' ? 'app__layout app__layout--graph' : 'app__layout'}>
                {agentsSubview === 'graph' && (
                  <div className="app__graph-panel">
                    <AgentGraph
                      root={root}
                      selectedId={selection.kind === 'edit' ? selection.agentId : null}
                      onSelect={(id) => setSelection({ kind: 'edit', agentId: id })}
                      onAddChild={(parentId) => setSelection({ kind: 'create', parentId })}
                      onChanged={reload}
                    />
                  </div>
                )}

                {agentsSubview === 'tree' && (
                  <aside className="app__sidebar">
                    <Tree
                      root={root}
                      selectedId={selection.kind === 'edit' ? selection.agentId : null}
                      onSelect={(id) => setSelection({ kind: 'edit', agentId: id })}
                      onAddChild={(parentId) => setSelection({ kind: 'create', parentId })}
                    />
                  </aside>
                )}

                <main className="app__main">
                  {selection.kind === 'edit' && selectedAgent && (
                    <AgentForm
                      mode="edit"
                      initial={selectedAgent}
                      availableTools={tools}
                      onCancel={() => setSelection({ kind: 'none' })}
                      onSaved={handleSaved}
                      onDeleted={handleSaved}
                    />
                  )}

                  {selection.kind === 'create' && (
                    <AgentForm
                      mode="create"
                      parentId={selection.parentId}
                      parentName={parentAgent?.name}
                      availableTools={tools}
                      onCancel={() => setSelection({ kind: 'none' })}
                      onSaved={handleSaved}
                      onDeleted={handleSaved}
                    />
                  )}

                  {selection.kind === 'none' && (
                    <p className="app__hint">
                      {auth.owner
                        ? 'Select an agent to edit it, or use + to add a specialist under it.'
                        : 'Select an agent to see how it is configured.'}
                    </p>
                  )}

                  <TestBox root={root} />
                </main>
              </div>
            )}
          </Suspense>
        </div>
      </div>
    </AuthContext.Provider>
  )
}

export default App
