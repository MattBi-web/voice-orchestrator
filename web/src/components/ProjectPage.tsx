import { lazy, Suspense, useEffect, useState } from 'react'
import type { Agent, CallStats, Catalog, ModelSettings, Project } from '../types'
import { api, ApiError } from '../api'
import { findAgent, findPath } from '../tree'
import { useOwner } from '../auth'
import type { ProjectTab } from '../route'
import { TopbarActions } from '../shell'
import { AgentForm } from './AgentForm'
import { TestPanel } from './TestPanel'
import { ModelsEditor } from './ModelsEditor'
import { PipelineStrip } from './PipelineStrip'
import { Orb } from './Orb'
import { Icon } from './Icon'
import { LEVELS, LEVEL_HEX } from './LevelChip'
import { resolve } from '../resolve'

const AgentGraph = lazy(() => import('./AgentGraph').then((m) => ({ default: m.AgentGraph })))
const Conversations = lazy(() => import('./Conversations').then((m) => ({ default: m.Conversations })))
const DeveloperPanel = lazy(() => import('./DeveloperPanel').then((m) => ({ default: m.DeveloperPanel })))

interface Props {
  pid: string
  tab: ProjectTab
  agentId?: string
  catalog: Catalog | null
  go: (tab: ProjectTab, agentId?: string) => void
  onCall: () => void
  onBack: () => void
  onChanged: () => void
}

/** Inside one agent (project). The sidebar lists its sections; this renders
 * the one in the route. A test panel slides in from the top bar's "Test"
 * on every section, so trying a change never means leaving the page. */
export function ProjectPage({ pid, tab, agentId, catalog, go, onCall, onBack, onChanged }: Props) {
  const [project, setProject] = useState<Project | null>(null)
  const [root, setRoot] = useState<Agent | null>(null)
  const [tools, setTools] = useState<string[]>([])
  const [creating, setCreating] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedCall, setSelectedCall] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  // The editor remounts with the saved agent, so the "Saved" note lives here.
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (!flash) return
    const t = window.setTimeout(() => setFlash(false), 2500)
    return () => window.clearTimeout(t)
  }, [flash])

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
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  if (error && !project) {
    return (
      <div className="empty">
        <span className="empty__icon">
          <Icon name="agents" />
        </span>
        <strong>This agent doesn’t exist</strong>
        <p>{error}</p>
        <button type="button" className="btn-secondary" onClick={onBack}>
          Back to all agents
        </button>
      </div>
    )
  }
  if (!project) return <p className="app__hint">Loading…</p>

  const selected = root ? (agentId && findAgent(root, agentId)) || root : null
  const workflow = (root?.children.length ?? 0) > 0
  const select = (id: string) => {
    setCreating(null)
    go('agent', id)
  }
  const saved = () => {
    setFlash(true)
    setCreating(null)
    reload()
    onChanged()
  }

  return (
    <div className={testing ? 'project project--testing' : 'project'}>
      <TopbarActions>
        {flash && <span className="topbar__note topbar__note--ok">Saved</span>}
        <button type="button" className={testing ? 'btn-secondary is-on' : 'btn-secondary'} onClick={() => setTesting((t) => !t)}>
          <Icon name="spark" />
          Test
        </button>
        <button type="button" className="btn-secondary" onClick={onCall}>
          <Icon name="phone" />
          Call
        </button>
      </TopbarActions>

      {error && <p className="error">{error}</p>}

      <Suspense fallback={<p className="app__hint">Loading…</p>}>
        {tab === 'overview' && root && <ProjectOverview project={project} root={root} catalog={catalog} go={go} onTest={() => setTesting(true)} />}

        {tab === 'agent' && root && selected && (
          <div className={workflow || creating ? 'workspace' : 'workspace workspace--single'}>
            {(workflow || creating) && (
              <AgentsRail
                pid={pid}
                root={root}
                selectedId={creating ? null : selected.id}
                creatingUnder={creating}
                onSelect={select}
                onAdd={(parentId) => setCreating(parentId)}
              />
            )}
            <div className="workspace__main">
              {creating ? (
                <AgentForm
                  key={`new-${creating}`}
                  pid={pid}
                  settings={project.settings}
                  catalog={catalog}
                  mode="create"
                  path={findPath(root, creating)}
                  onSelectAgent={select}
                  parentId={creating}
                  parentName={findAgent(root, creating)?.name}
                  availableTools={tools}
                  onCancel={() => setCreating(null)}
                  onSaved={saved}
                  onDeleted={reload}
                />
              ) : (
                <AgentForm
                  key={`${selected.id}-${project.updated_at}`}
                  pid={pid}
                  settings={project.settings}
                  catalog={catalog}
                  mode="edit"
                  path={findPath(root, selected.id)}
                  onSelectAgent={select}
                  initial={selected}
                  availableTools={tools}
                  onCancel={() => select(root.id)}
                  onSaved={saved}
                  onDeleted={() => {
                    select(root.id)
                    saved()
                  }}
                />
              )}
              {!workflow && !creating && <GrowHint root={root} onAdd={() => setCreating(root.id)} />}
            </div>
          </div>
        )}

        {tab === 'workflow' && root && (
          <WorkflowCanvas
            pid={pid}
            root={root}
            selectedId={selected?.id ?? root.id}
            onSelect={(id) => go('workflow', id)}
            onOpen={(id) => go('agent', id)}
            onAdd={(parentId) => {
              setCreating(parentId)
              go('agent', parentId)
            }}
            onChanged={reload}
          />
        )}

        {tab === 'models' && (
          <ProjectSettings
            project={project}
            catalog={catalog}
            onSaved={() => {
              reload()
              onChanged()
            }}
            onDeleted={onBack}
          />
        )}

        {tab === 'calls' && (
          <>
            <PageTitle title="Calls" lede={`Every call and text test on ${project.name}, turn by turn.`} />
            <Conversations project={pid} selectedCallId={selectedCall} onSelectCall={setSelectedCall} />
          </>
        )}

        {tab === 'developer' && (
          <>
            <PageTitle title="Developer" lede="Ids, the pipeline the server will run, the configuration as code, and the API." />
            <DeveloperPanel project={project} root={root} agentId={selected?.id ?? root?.id ?? ''} />
          </>
        )}
      </Suspense>

      {testing && root && (
        <aside className="drawer" aria-label="Test this agent">
          <div className="drawer__head">
            <h2>Test {project.name}</h2>
            <button type="button" className="btn-icon" aria-label="Close" onClick={() => setTesting(false)}>
              <Icon name="x" />
            </button>
          </div>
          <TestPanel key={`${pid}-${project.updated_at}`} pid={pid} root={root} />
        </aside>
      )}
    </div>
  )
}

function PageTitle({ title, lede, actions }: { title: string; lede?: string; actions?: React.ReactNode }) {
  return (
    <header className="page__head">
      <div>
        <h1>{title}</h1>
        {lede && <p className="page__lede">{lede}</p>}
      </div>
      {actions && <div className="page__actions">{actions}</div>}
    </header>
  )
}

/** The list of a workflow's agents, as an indented column, like a file tree. */
function AgentsRail({
  pid,
  root,
  selectedId,
  creatingUnder,
  onSelect,
  onAdd,
}: {
  pid: string
  root: Agent
  selectedId: string | null
  creatingUnder: string | null
  onSelect: (id: string) => void
  onAdd: (parentId: string) => void
}) {
  const owner = useOwner()
  const rows: { agent: Agent; depth: number }[] = []
  const walk = (a: Agent, depth: number) => {
    rows.push({ agent: a, depth })
    a.children.forEach((c) => walk(c, depth + 1))
  }
  walk(root, 0)
  return (
    <nav className="rail" aria-label="Agents in this workflow">
      <div className="rail__title">Agents</div>
      {rows.map(({ agent, depth }) => (
        <div key={agent.id} className="rail__row" style={{ paddingLeft: depth * 14 }}>
          <button
            type="button"
            className="rail__item"
            aria-current={selectedId === agent.id ? 'true' : undefined}
            onClick={() => onSelect(agent.id)}
          >
            <Orb seed={`${pid}/${agent.id}`} size={16} />
            <span className="rail__name">{agent.name || agent.id}</span>
            {agent.eligibility && <span className="rail__gate" title={agent.eligibility}>gate</span>}
          </button>
          {owner && (
            <button type="button" className="rail__add" title={`Add a specialist under ${agent.name}`} onClick={() => onAdd(agent.id)}>
              <Icon name="plus" />
            </button>
          )}
          {creatingUnder === agent.id && (
            <div className="rail__new" style={{ marginLeft: 14 }}>
              <Orb seed="new" size={16} />
              New specialist
            </div>
          )}
        </div>
      ))}
    </nav>
  )
}

function GrowHint({ root, onAdd }: { root: Agent; onAdd: () => void }) {
  const owner = useOwner()
  if (!owner) return null
  return (
    <button type="button" className="grow" onClick={onAdd}>
      <Icon name="flow" />
      <span>
        <strong>Turn this into a workflow</strong>
        Add a specialist: {root.name} becomes a receptionist that hands calls over, and the router decides who answers.
      </span>
    </button>
  )
}

/** The project at a glance: numbers, how the receptionist is built, where
 * the router's decisions come from, and the agents. */
function ProjectOverview({
  project,
  root,
  catalog,
  go,
  onTest,
}: {
  project: Project
  root: Agent
  catalog: Catalog | null
  go: (tab: ProjectTab, agentId?: string) => void
  onTest: () => void
}) {
  const [stats, setStats] = useState<CallStats | null>(null)
  useEffect(() => {
    api
      .getCallStats(true, 14, project.id)
      .then(setStats)
      .catch(() => setStats(null))
  }, [project.id])

  const totals = stats?.resolved_by_totals ?? {}
  const decisions = Object.values(totals).reduce((a, b) => a + b, 0)
  const agents: { agent: Agent; depth: number }[] = []
  const walk = (a: Agent, d: number) => {
    agents.push({ agent: a, depth: d })
    a.children.forEach((c) => walk(c, d + 1))
  }
  walk(root, 0)

  return (
    <div className="pov">
      <header className="pov__head">
        <Orb seed={project.id} size={44} />
        <div>
          <h1>{project.name}</h1>
          <p className="page__lede">{project.description || (project.kind === 'single' ? 'A single agent.' : 'A workflow of agents.')}</p>
        </div>
      </header>

      <div className="kpis">
        <Kpi label="Calls" value={stats ? String(stats.total_calls) : '—'} />
        <Kpi label="Average length" value={stats ? `${stats.avg_duration_seconds.toFixed(0)} s` : '—'} />
        <Kpi label="Handed over" value={stats ? `${Math.round(stats.handoff_rate * 100)}%` : '—'} />
        <Kpi
          label="Decided without a model"
          value={decisions ? `${Math.round((((totals.gate_only ?? 0) + (totals.pattern ?? 0)) / decisions) * 100)}%` : '—'}
        />
      </div>

      {decisions > 0 && (
        <section className="pov__block">
          <h2>Who decided each turn</h2>
          <div className="levelbar" role="img" aria-label="Share of routing decisions by router level">
            {(['gate_only', 'pattern', 'llm_fallback'] as const).map((k) =>
              totals[k] ? <span key={k} style={{ flex: totals[k], background: LEVEL_HEX[k] }} title={`${LEVELS[k].label}: ${totals[k]}`} /> : null,
            )}
          </div>
          <ul className="levelbar__legend">
            {(['gate_only', 'pattern', 'llm_fallback'] as const).map((k) => (
              <li key={k}>
                <i style={{ background: LEVEL_HEX[k] }} />
                {LEVELS[k].label} <strong>{totals[k] ?? 0}</strong>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="pov__block">
        <div className="pov__blockhead">
          <h2>How {root.name} is built</h2>
          <button type="button" className="btn-secondary" onClick={() => go('agent', root.id)}>
            Edit
          </button>
        </div>
        <PipelineStrip
          resolved={resolve(root, project.settings, catalog, true)}
          toolCount={root.tools.length}
          specialists={root.children.length}
          hasGate={root.children.some((c) => c.eligibility)}
          onOpen={() => go('agent', root.id)}
        />
      </section>

      <section className="pov__block">
        <div className="pov__blockhead">
          <h2>{project.kind === 'single' ? 'Agent' : 'Agents'}</h2>
          <button type="button" className="btn-secondary" onClick={onTest}>
            <Icon name="spark" />
            Test
          </button>
        </div>
        <ul className="cards">
          {agents.map(({ agent, depth }) => (
            <li key={agent.id}>
              <button type="button" className="card" onClick={() => go('agent', agent.id)}>
                <Orb seed={`${project.id}/${agent.id}`} size={30} />
                <span>
                  <strong>{agent.name}</strong>
                  <small>
                    {depth === 0 ? 'Answers first' : agent.triggers.length ? `${agent.triggers.length} keywords` : 'Picked by the model'}
                    {agent.eligibility ? ', behind a gate' : ''}
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

/** The workflow on a dotted canvas, with the selected agent on the right. */
function WorkflowCanvas({
  pid,
  root,
  selectedId,
  onSelect,
  onOpen,
  onAdd,
  onChanged,
}: {
  pid: string
  root: Agent
  selectedId: string
  onSelect: (id: string) => void
  onOpen: (id: string) => void
  onAdd: (parentId: string) => void
  onChanged: () => void
}) {
  const owner = useOwner()
  const agent = findAgent(root, selectedId) ?? root
  return (
    <div className="canvas">
      <div className="canvas__board">
        <AgentGraph pid={pid} root={root} selectedId={agent.id} onSelect={onSelect} onAddChild={onAdd} onChanged={onChanged} />
      </div>
      <aside className="canvas__side">
        <div className="canvas__agent">
          <Orb seed={`${pid}/${agent.id}`} size={34} />
          <div>
            <h2>{agent.name}</h2>
            <code>{agent.id}</code>
          </div>
        </div>
        <p className="canvas__desc">{agent.description || 'No description.'}</p>
        <dl className="canvas__facts">
          <dt>Reached by</dt>
          <dd>
            {agent.parent_id === null
              ? 'Answers first'
              : [agent.eligibility && `gate (${agent.eligibility})`, agent.triggers.length ? `${agent.triggers.length} keywords` : 'the router’s model']
                  .filter(Boolean)
                  .join(', then ')}
          </dd>
          <dt>Tools</dt>
          <dd>{agent.tools.length ? agent.tools.map((t) => t.id).join(', ') : 'None'}</dd>
          <dt>Knowledge</dt>
          <dd>{agent.knowledge.length ? agent.knowledge.join(', ') : 'None'}</dd>
          <dt>Specialists</dt>
          <dd>{agent.children.length ? agent.children.map((c) => c.name).join(', ') : 'None'}</dd>
        </dl>
        <div className="canvas__actions">
          <button type="button" className="btn-primary" onClick={() => onOpen(agent.id)}>
            Edit agent
          </button>
          {owner && (
            <button type="button" className="btn-secondary" onClick={() => onAdd(agent.id)}>
              <Icon name="plus" />
              Add specialist
            </button>
          )}
        </div>
      </aside>
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

  const save = async () => {
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
    <form
      className="settings"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      {owner && (
        <TopbarActions>
          {dirty && <span className="topbar__note">Unsaved changes</span>}
          {saved && !dirty && <span className="topbar__note topbar__note--ok">Saved</span>}
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
              Discard
            </button>
          )}
          <button type="button" className="btn-primary" disabled={saving || !dirty} onClick={save}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </TopbarActions>
      )}
      <PageTitle title="Models" lede="The defaults every agent in this project starts from. An agent can override any piece on its own page." />
      {error && <p className="error">{error}</p>}
      <fieldset className="ro-fieldset" disabled={!owner}>
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
      </fieldset>
      {owner && (
        <section className="settings__block editor__danger">
          <div className="editor__label">
            <h2>Delete {project.name}</h2>
            <p>Removes every agent in it. Its recorded calls stay in Calls.</p>
          </div>
          <button type="button" className="btn-danger" onClick={remove}>
            Delete {project.name}
          </button>
        </section>
      )}
    </form>
  )
}
