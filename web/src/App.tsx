import { useEffect, useState } from 'react'
import type { Agent } from './types'
import { api, ApiError } from './api'
import { findAgent } from './tree'
import { Tree } from './components/Tree'
import { AgentForm } from './components/AgentForm'
import { TestBox } from './components/TestBox'
import { VoiceTestConsole } from './components/VoiceTestConsole'
import { Dashboard } from './components/Dashboard'
import { McpServersPanel } from './components/McpServersPanel'
import './App.css'

type Selection =
  | { kind: 'none' }
  | { kind: 'edit'; agentId: string }
  | { kind: 'create'; parentId: string }

type View = 'builder' | 'voice' | 'dashboard'

function App() {
  const [view, setView] = useState<View>('builder')
  const [root, setRoot] = useState<Agent | null>(null)
  const [tools, setTools] = useState<string[]>([])
  const [selection, setSelection] = useState<Selection>({ kind: 'none' })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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
          <code>config/agents.yaml</code>, then independent of it).
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
        </nav>
      </header>

      {error && <p className="error app__error">{error}</p>}

      {view === 'voice' ? (
        <VoiceTestConsole />
      ) : view === 'dashboard' ? (
        <Dashboard />
      ) : loading ? (
        <p>Loading…</p>
      ) : (
        <div className="app__layout">
          <aside className="app__sidebar">
            <Tree
              root={root}
              selectedId={selection.kind === 'edit' ? selection.agentId : null}
              onSelect={(id) => setSelection({ kind: 'edit', agentId: id })}
              onAddChild={(parentId) => setSelection({ kind: 'create', parentId })}
            />
          </aside>

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
