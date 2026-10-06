import { useEffect, useRef, useState } from 'react'
import type { Catalog, Project, Template } from '../types'
import { api, ApiError } from '../api'
import { useOwner } from '../auth'
import { formatWhen } from './LevelChip'
import { Orb } from './Orb'

interface Props {
  catalog: Catalog | null
  /** #/new-agent: open with the create dialog showing. */
  creating?: boolean
  onCloseCreate?: () => void
  onOpen: (pid: string) => void
  onCall: (pid: string) => void
}

/** Blocco 8: the agents page. Each row is one phone line: a single agent or
 * a workflow of agents, with the models it runs on. */
export function ProjectsList({ catalog, creating: createRoute = false, onCloseCreate, onOpen, onCall }: Props) {
  const owner = useOwner()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(createRoute)
  useEffect(() => setCreating(createRoute), [createRoute])

  useEffect(() => {
    api
      .listProjects()
      .then((r) => setProjects(r.projects))
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [])

  const label = (component: 'stt' | 'tts' | 'llm', id: string) => catalog?.[component].find((p) => p.id === id)?.label ?? id
  const voice = (p: Project) => {
    const provider = catalog?.tts.find((x) => x.id === p.settings.tts_provider)
    const v = provider?.voices.find((x) => x.id === p.settings.voice_id)
    return `${label('tts', p.settings.tts_provider)}, ${v ? v.label.split(' (')[0] : p.settings.voice_id || 'default voice'}`
  }
  const model = (p: Project) =>
    !p.settings.llm_provider || p.settings.llm_provider === 'fake'
      ? 'No model'
      : `${label('llm', p.settings.llm_provider)}${p.settings.llm_model ? `, ${p.settings.llm_model}` : ''}`

  return (
    <div className="projects">
      <header className="page__head">
        <div>
          <h1>Agents</h1>
          <p className="page__lede">
            Each agent is one phone line: a single agent that answers the whole call, or a workflow where a
            receptionist hands the call to specialists.
          </p>
        </div>
        {owner && (
          <div className="page__actions">
            <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
              New agent
            </button>
          </div>
        )}
      </header>

      {error && <p className="error">{error}</p>}
      {projects === null && !error && <p className="app__hint">Loading…</p>}

      {projects && projects.length === 0 && (
        <div className="projects__empty">
          <p>No agents yet.</p>
          {owner && (
            <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
              Create your first agent
            </button>
          )}
        </div>
      )}

      {projects && projects.length > 0 && (
        <table className="projects__table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Type</th>
              <th scope="col">Voice</th>
              <th scope="col">Language model</th>
              <th scope="col" className="num">
                Calls
              </th>
              <th scope="col">Edited</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id} onClick={() => onOpen(p.id)}>
                <td className="projects__name">
                  <Orb seed={p.id} size={30} />
                  <span>
                    <a
                      href={`#/agents/${encodeURIComponent(p.id)}/build`}
                      onClick={(e) => e.stopPropagation()}
                      className="projects__link"
                    >
                      {p.name}
                    </a>
                    {p.description && <span className="projects__desc">{p.description}</span>}
                  </span>
                </td>
                <td>{p.kind === 'single' ? 'Single agent' : `Workflow, ${p.agent_count} agents`}</td>
                <td>{voice(p)}</td>
                <td>{model(p)}</td>
                <td className="num">{p.call_count ?? 0}</td>
                <td className="projects__when">{formatWhen(p.updated_at)}</td>
                <td className="projects__actions">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={(e) => {
                      e.stopPropagation()
                      onCall(p.id)
                    }}
                  >
                    Call
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && (
        <NewAgentDialog
          onClose={() => {
            setCreating(false)
            onCloseCreate?.()
          }}
          onCreated={(pid) => onOpen(pid)}
        />
      )}
    </div>
  )
}

/** The shape of a project in miniature: one node, or a node with branches. */
export function Glyph({ kind, count }: { kind: 'single' | 'workflow'; count: number }) {
  if (kind === 'single') {
    return (
      <svg className="glyph" viewBox="0 0 28 28" aria-hidden>
        <circle cx="14" cy="14" r="5" />
      </svg>
    )
  }
  const n = Math.min(Math.max(count - 1, 2), 4)
  const ys = Array.from({ length: n }, (_, i) => 5 + (i * 18) / (n - 1))
  return (
    <svg className="glyph" viewBox="0 0 28 28" aria-hidden>
      {ys.map((y) => (
        <path key={y} d={`M9 14 C14 14 14 ${y} 20 ${y}`} />
      ))}
      <circle cx="7" cy="14" r="3.5" />
      {ys.map((y) => (
        <circle key={`n${y}`} cx="22" cy={y} r="2.5" />
      ))}
    </svg>
  )
}

function NewAgentDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (pid: string) => void }) {
  const ref = useRef<HTMLDialogElement | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [template, setTemplate] = useState<Template['id']>('single')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ref.current?.showModal()
    api
      .listTemplates()
      .then((r) => setTemplates(r.templates))
      .catch(() => setTemplates([]))
  }, [])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const p = await api.createProject({ name, template })
      onCreated(p.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} aria-labelledby="new-agent-title">
      <form onSubmit={create}>
        <h2 id="new-agent-title">New agent</h2>
        <label className="field">
          <span className="field__label">Name</span>
          <input autoFocus required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Pizzeria booking line" />
        </label>
        <fieldset className="choices">
          <legend className="field__label">Start from</legend>
          {templates.map((t) => (
            <label key={t.id} className={template === t.id ? 'choice choice--on' : 'choice'}>
              <input type="radio" name="template" value={t.id} checked={template === t.id} onChange={() => setTemplate(t.id)} />
              <Glyph kind={t.agent_count > 1 ? 'workflow' : 'single'} count={t.agent_count} />
              <span className="choice__text">
                <strong>{t.name}</strong>
                <span>{t.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {error && <p className="error">{error}</p>}
        <div className="dialog__actions">
          <button type="button" className="btn-secondary" onClick={() => ref.current?.close()}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !name.trim()}>
            {busy ? 'Creating…' : 'Create agent'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
