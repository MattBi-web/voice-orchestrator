import { useEffect, useState } from 'react'
import type { Agent } from './types'
import { api, ApiError } from './api'
import { findAgent } from './tree'
import { Tree } from './components/Tree'
import { AgentGraph } from './components/AgentGraph'
import { AgentForm } from './components/AgentForm'
import { TestBox } from './components/TestBox'
import { VoiceTestConsole } from './components/VoiceTestConsole'
import { Dashboard } from './components/Dashboard'
import { McpServersPanel } from './components/McpServersPanel'
import { Conversations } from './components/Conversations'
import './App.css'

type Selection =
  | { kind: 'none' }
  | { kind: 'edit'; agentId: string }
  | { kind: 'create'; parentId: string }

type View = 'builder' | 'voice' | 'dashboard' | 'conversations'
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
    <div className="app">
      <header className="app__header">
        <h1>voice-orchestrator — agent builder</h1>
        <p className="app__subtitle">
          Editing the SQLite-backed agent family (seeded once from{' '}
          <code>config/agents.yaml</code>, then independent of it — "Esporta" writes it back on demand).
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

      {error && <p className="error app__error">{error}</p>}

      {view === 'voice' ? (
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
            <div className="app__export">
              <button type="button" className="btn-link" onClick={handleExport} disabled={exporting}>
                {exporting ? 'Esporto…' : '↓ Esporta verso agents.yaml'}
              </button>
              {exportResult && <p className="app__export-result">{exportResult}</p>}
            </div>
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
              <p className="app__export-hint">
                "Esporta" scrive la famiglia attuale su agents.yaml — così la CLI e il test vocale la vedono. Non
                automatico — va rifatto a ogni cambio che vuoi propagare.
              </p>
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
          </main>
        </div>
      )}
    </div>
  )
}

export default App
