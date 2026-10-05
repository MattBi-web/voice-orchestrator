import { lazy, Suspense, useEffect, useState } from 'react'
import type { Agent, Catalog, ModelSettings, Project } from '../types'
import { api, ApiError } from '../api'
import { findAgent, findPath } from '../tree'
import { useOwner } from '../auth'
import type { ProjectTab } from '../route'
import { Tree } from './Tree'
import { AgentForm, type AgentDraft, type AgentTab } from './AgentForm'
import { PipelineStrip } from './PipelineStrip'
import { resolve } from '../resolve'
import { TestPanel } from './TestPanel'
import { ModelsEditor } from './ModelsEditor'
import { Glyph } from './ProjectsList'

const AgentGraph = lazy(() => import('./AgentGraph').then((m) => ({ default: m.AgentGraph })))
const Conversations = lazy(() => import('./Conversations').then((m) => ({ default: m.Conversations })))
const DeveloperPanel = lazy(() => import('./DeveloperPanel').then((m) => ({ default: m.DeveloperPanel })))

type Selection = { kind: 'edit'; agentId: string } | { kind: 'create'; parentId: string }

const TABS: { id: ProjectTab; label: string }[] = [
  { id: 'build', label: 'Build' },
  { id: 'models', label: 'Models' },
  { id: 'calls', label: 'Calls' },
  { id: 'developer', label: 'Developer' },
]

interface Props {
  pid: string
  tab: ProjectTab
  agentId?: string
  catalog: Catalog | null
  go: (tab: ProjectTab, agentId?: string) => void
  onCall: () => void
  onBack: () => void
}

/** Blocco 8: one agent (project). Build: the agents, each with its pipeline
 * and settings, plus a test panel. Models: the defaults every agent
 * inherits. Calls: this project's calls. Developer: ids, config, API. */
export function ProjectPage({ pid, tab, agentId, catalog, go, onCall, onBack }: Props) {
  const owner = useOwner()
  const [project, setProject] = useState<Project | null>(null)
  const [root, setRoot] = useState<Agent | null>(null)
  const [tools, setTools] = useState<string[]>([])
  const [creating, setCreating] = useState<string | null>(null)
  const [subview, setSubview] = useState<'list' | 'graph'>('list')
  const [error, setError] = useState<string | null>(null)
  const [selectedCall, setSelectedCall] = useState<string | null>(null)
  const [agentTab, setAgentTab] = useState<AgentTab>('behavior')
  const [draft, setDraft] = useState<AgentDraft | null>(null)

  const reload = async () => {
    try {
      const [p, tree, toolList] = await Promise.all([api.getProject(pid), api.getTree(pid), api.listTools()])
      setProject(p)
      setRoot(tree.root)
      setTools(toolList.tools)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  useEffect(() => {
    setProject(null)
    setRoot(null)
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  if (error && !project) {
    return (
      <div className="project">
        <p className="error">{error}</p>
        <button type="button" className="btn-secondary" onClick={onBack}>
          Back to agents
        </button>
      </div>
    )
  }
  if (!project) return <p className="app__hint">Loading…</p>

  const selection: Selection | null = creating
    ? { kind: 'create', parentId: creating }
    : root
      ? { kind: 'edit', agentId: agentId && findAgent(root, agentId) ? agentId : root.id }
      : null
  const selected = selection?.kind === 'edit' ? findAgent(root, selection.agentId) : null
  const workflow = (root?.children.length ?? 0) > 0
  const select = (id: string) => {
    setCreating(null)
    go('build', id)
  }

  return (
    <div className="project">
      <header className="project__head">
        <nav className="project__crumbs" aria-label="Breadcrumb">
          <a href="#/agents">Agents</a>
          <span aria-hidden> / </span>
        </nav>
        <div className="project__title">
          <Glyph kind={project.kind} count={project.agent_count} />
          <div>
            <h1>{project.name}</h1>
            <p className="project__kind">
              {project.kind === 'single' ? 'Single agent' : `Workflow of ${project.agent_count} agents`}
              {project.description && <span className="project__desc">{project.description}</span>}
            </p>
          </div>
          <div className="project__actions">
            <button type="button" className="btn-primary" onClick={onCall}>
              Call this agent
            </button>
          </div>
        </div>
        <div className="tabs" role="tablist" aria-label="Agent sections">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={tab === t.id ? 'tab tab--active' : 'tab'}
              onClick={() => go(t.id, t.id === 'build' ? selected?.id : undefined)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      <Suspense fallback={<p className="app__hint">Loading…</p>}>
        {tab === 'build' && root && selection && (
          <div className={workflow ? (subview === 'graph' ? 'agents agents--graph' : 'agents') : 'agents agents--single'}>
            {workflow && (
              <div className="agents__switch" role="tablist" aria-label="Show agents as">
                {(['list', 'graph'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    role="tab"
                    aria-selected={subview === v}
                    className={subview === v ? 'app__tab app__tab--active' : 'app__tab'}
                    onClick={() => setSubview(v)}
                  >
                    {v === 'list' ? 'List' : 'Graph'}
                  </button>
                ))}
              </div>
            )}
            {draft && (
              <section className="agents__pipe" aria-label="Pipeline">
                <p className="agents__pipe-title">
                  How <strong>{draft.name || 'the new agent'}</strong> is built, in the order a turn goes through it
                </p>
                <PipelineStrip
                  resolved={resolve(draft, project.settings, catalog, selection.kind === 'edit' && selected?.id === root.id)}
                  toolCount={draft.tools.filter((t) => t.id.trim()).length}
                  specialists={selection.kind === 'edit' && selected ? selected.children.length : 0}
                  hasGate={selection.kind === 'edit' && selected ? selected.children.some((c) => c.eligibility) : false}
                  onOpen={setAgentTab}
                />
              </section>
            )}
            {workflow && subview === 'graph' && (
              <div className="agents__graph">
                <AgentGraph
                  pid={pid}
                  root={root}
                  selectedId={selection.kind === 'edit' ? selection.agentId : null}
                  onSelect={select}
                  onAddChild={(parentId) => setCreating(parentId)}
                  onChanged={reload}
                />
              </div>
            )}
            {workflow && subview === 'list' && (
              <aside className="agents__tree">
                <Tree
                  root={root}
                  selectedId={selection.kind === 'edit' ? selection.agentId : null}
                  onSelect={select}
                  onAddChild={(parentId) => setCreating(parentId)}
                />
              </aside>
            )}

            <main className="agents__page">
              {selection.kind === 'edit' && selected && (
                <AgentForm
                  key={`${selected.id}-${project.updated_at}`}
                  pid={pid}
                  tab={agentTab}
                  onTab={setAgentTab}
                  onDraft={setDraft}
                  settings={project.settings}
                  catalog={catalog}
                  mode="edit"
                  path={findPath(root, selected.id)}
                  onSelectAgent={select}
                  initial={selected}
                  availableTools={tools}
                  onCancel={() => select(root.id)}
                  onSaved={reload}
                  onDeleted={() => {
                    select(root.id)
                    reload()
                  }}
                />
              )}
              {selection.kind === 'create' && (
                <AgentForm
                  key={`new-${selection.parentId}`}
                  pid={pid}
                  tab={agentTab}
                  onTab={setAgentTab}
                  onDraft={setDraft}
                  settings={project.settings}
                  catalog={catalog}
                  mode="create"
                  path={findPath(root, selection.parentId)}
                  onSelectAgent={select}
                  parentId={selection.parentId}
                  parentName={findAgent(root, selection.parentId)?.name}
                  availableTools={tools}
                  onCancel={() => setCreating(null)}
                  onSaved={() => {
                    setCreating(null)
                    reload()
                  }}
                  onDeleted={reload}
                />
              )}
              {!workflow && owner && selection.kind === 'edit' && (
                <button type="button" className="agents__grow" onClick={() => setCreating(root.id)}>
                  Add a specialist: {root.name} becomes a receptionist that hands calls over
                </button>
              )}
            </main>

            <aside className="agents__test">
              <TestPanel key={`${pid}-${project.updated_at}`} pid={pid} root={root} />
            </aside>
          </div>
        )}

        {tab === 'models' && <ProjectSettings project={project} catalog={catalog} onSaved={reload} onDeleted={onBack} />}

        {tab === 'calls' && <Conversations project={pid} selectedCallId={selectedCall} onSelectCall={setSelectedCall} />}

        {tab === 'developer' && <DeveloperPanel project={project} root={root} agentId={selected?.id ?? root?.id ?? ''} />}
      </Suspense>
    </div>
  )
}

function ProjectSettings({
  project,
  catalog,
  onSaved,
  onDeleted,
}: {
  project: Project
  catalog: Catalog | null
  onSaved: () => void
  onDeleted: () => void
}) {
  const owner = useOwner()
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description)
  const [settings, setSettings] = useState<ModelSettings>(project.settings)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dirty =
    name !== project.name || description !== project.description || JSON.stringify(settings) !== JSON.stringify(project.settings)

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.updateProject(project.id, { name, description, settings })
      setSaved(true)
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!confirm(`Delete "${project.name}" and all its agents? Its recorded calls stay in Calls.`)) return
    try {
      await api.deleteProject(project.id)
      onDeleted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <form className="settings" onSubmit={save}>
      <fieldset className="ro-fieldset" disabled={!owner}>
        <section className="settings__block">
          <h2>Name and description</h2>
          <label className="field">
            <span className="field__label">Name</span>
            <input required value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            <span className="field__label">Description</span>
            <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
        </section>
        <section className="settings__block">
          <h2>Default models</h2>
          <p className="settings__lede">
            Every agent in this project uses these unless it overrides a piece on its own Models tab.
          </p>
          <ModelsEditor
            mode="project"
            value={settings}
            project={settings}
            catalog={catalog}
            onChange={(patch) => {
              setSaved(false)
              setSettings((s) => ({ ...s, ...patch }))
            }}
          />
        </section>
      </fieldset>
      {error && <p className="error">{error}</p>}
      {owner && (
        <div className={dirty ? 'form-actions form-actions--dirty' : 'form-actions'}>
          <button type="submit" className="btn-primary" disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          {dirty && (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setName(project.name)
                setDescription(project.description)
                setSettings(project.settings)
              }}
            >
              Discard changes
            </button>
          )}
          {saved && !dirty && <span className="form-actions__ok">Saved</span>}
          <button type="button" className="btn-danger" onClick={remove}>
            Delete {project.name}
          </button>
        </div>
      )}
    </form>
  )
}
