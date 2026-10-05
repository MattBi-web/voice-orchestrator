import { lazy, Suspense, useEffect, useState } from 'react'
import type { Agent } from './types'
import { api, ApiError } from './api'
import { findAgent } from './tree'
import { Tree } from './components/Tree'
import { AgentForm } from './components/AgentForm'
import { TestBox } from './components/TestBox'
import { McpServersPanel } from './components/McpServersPanel'
import { WebhookToolsPanel } from './components/WebhookToolsPanel'
import { AuthBar } from './components/AuthBar'
import { AuthContext, type AuthState } from './auth'
import './App.css'

// D9: every tab except the agent builder's tree view loads on demand. The
// two heavy dependencies sit behind these — livekit-client (voice console)
// and recharts (dashboard) — so the first page load no longer pays for them.
const AgentGraph = lazy(() => import('./components/AgentGraph').then((m) => ({ default: m.AgentGraph })))
const VoiceTestConsole = lazy(() => import('./components/VoiceTestConsole').then((m) => ({ default: m.VoiceTestConsole })))
const Dashboard = lazy(() => import('./components/Dashboard').then((m) => ({ default: m.Dashboard })))
const Conversations = lazy(() => import('./components/Conversations').then((m) => ({ default: m.Conversations })))
const KnowledgeBase = lazy(() => import('./components/KnowledgeBase').then((m) => ({ default: m.KnowledgeBase })))

type Selection =
  | { kind: 'none' }
  | { kind: 'edit'; agentId: string }
  | { kind: 'create'; parentId: string }

type View = 'builder' | 'knowledge' | 'voice' | 'dashboard' | 'conversations'
type BuilderSubview = 'tree' | 'graph'

function App() {
  const [view, setView] = useState<View>('builder')
  const [builderSubview, setBuilderSubview] = useState<BuilderSubview>('tree')
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

  const handleDeleted = () => {
    setSelection({ kind: 'none' })
    reload()
  }

  const handleExport = async () => {
    if (
      !confirm(
        'Sovrascrive config/agents.yaml — il file che chat/route/eval da CLI e il worker vocale leggono — ' +
          'con la famiglia attuale del builder. Il file è tracciato da git: se hai modifiche lì non committate, ' +
          'questa azione le perde. Continuare?'
      )
    ) {
      return
    }
    setExporting(true)
    setExportResult(null)
    setError(null)
    try {
      const result = await api.exportAgents()
      setExportResult(`Esportati ${result.agent_count} agenti in ${result.path}.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setExporting(false)
    }
  }

  const selectedAgent =
    selection.kind === 'edit' ? findAgent(root, selection.agentId) : undefined
  const parentAgent =
    selection.kind === 'create' ? findAgent(root, selection.parentId) : undefined

  return (
    <AuthContext.Provider value={auth}>
    <div className="app">
      <header className="app__header">
        <div className="app__titlebar">
          <h1>voice-orchestrator — agent builder</h1>
          <AuthBar auth={auth} onChange={setAuth} />
        </div>
        <p className="app__subtitle">
          Una famiglia di voice agent con router a 3 livelli: configura gli agenti, provali in testo e in voce, guarda
          conversazioni e analisi.
        </p>
        <nav className="app__tabs">
          <button
            type="button"
            className={view === 'builder' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setView('builder')}
          >
            Agent builder
          </button>
          <button
            type="button"
            className={view === 'knowledge' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setView('knowledge')}
          >
            Knowledge base
          </button>
          <button
            type="button"
            className={view === 'voice' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setView('voice')}
          >
            Test live (voce)
          </button>
          <button
            type="button"
            className={view === 'dashboard' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setView('dashboard')}
          >
            Dashboard
          </button>
          <button
            type="button"
            className={view === 'conversations' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setView('conversations')}
          >
            Conversazioni
          </button>
        </nav>
      </header>

      {auth.authRequired && !auth.owner && (
        <p className="app__readonly">
          Demo in sola lettura: puoi esplorare agenti, knowledge base, conversazioni e dashboard, provare il box "Try it"
          e chiamare l'agente dalla tab "Test live (voce)". Le modifiche sono riservate al proprietario.
        </p>
      )}
      {error && <p className="error app__error">{error}</p>}

      <Suspense fallback={<p className="app__hint">Loading…</p>}>
      {view === 'knowledge' ? (
        <KnowledgeBase root={root} />
      ) : view === 'voice' ? (
        <VoiceTestConsole />
      ) : view === 'dashboard' ? (
        <Dashboard
          onOpenCall={(callId) => {
            setSelectedCallId(callId)
            setView('conversations')
          }}
        />
      ) : view === 'conversations' ? (
        <Conversations selectedCallId={selectedCallId} onSelectCall={setSelectedCallId} />
      ) : loading ? (
        <p>Loading…</p>
      ) : (
        <div className={builderSubview === 'graph' ? 'app__layout app__layout--graph' : 'app__layout'}>
          <div className="app__builder-topbar">
            <div className="app__subtabs">
              <button
                type="button"
                className={builderSubview === 'tree' ? 'app__tab app__tab--active' : 'app__tab'}
                onClick={() => setBuilderSubview('tree')}
              >
                Albero
              </button>
              <button
                type="button"
                className={builderSubview === 'graph' ? 'app__tab app__tab--active' : 'app__tab'}
                onClick={() => setBuilderSubview('graph')}
              >
                Grafo
              </button>
            </div>
            {auth.owner && (
              <div className="app__export">
                <button type="button" className="btn-link" onClick={handleExport} disabled={exporting}>
                  {exporting ? 'Esporto…' : '↓ Esporta verso agents.yaml'}
                </button>
                {exportResult && <p className="app__export-result">{exportResult}</p>}
              </div>
            )}
          </div>

          {builderSubview === 'graph' && (
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

          {builderSubview === 'tree' && (
            <aside className="app__sidebar">
              <Tree
                root={root}
                selectedId={selection.kind === 'edit' ? selection.agentId : null}
                onSelect={(id) => setSelection({ kind: 'edit', agentId: id })}
                onAddChild={(parentId) => setSelection({ kind: 'create', parentId })}
              />
              {auth.owner && (
                <p className="app__export-hint">
                  "Esporta" scrive la famiglia attuale su agents.yaml, per la CLI. Il worker vocale online legge
                  direttamente il database: lì ogni salvataggio è già attivo dalla chiamata successiva.
                </p>
              )}
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
                onDeleted={handleDeleted}
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
                onDeleted={handleDeleted}
              />
            )}

            {selection.kind === 'none' && (
              <p className="app__hint">
                Select an agent on the left to edit it, or click its{' '}
                <strong>+</strong> to add a child.
              </p>
            )}

            <TestBox root={root} />

            <McpServersPanel onChanged={reload} />
            <WebhookToolsPanel onChanged={reload} />
          </main>
        </div>
      )}
      </Suspense>
    </div>
    </AuthContext.Provider>
  )
}

export default App
