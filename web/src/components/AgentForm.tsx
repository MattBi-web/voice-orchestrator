import { useEffect, useState } from 'react'
import type { Agent, Catalog, ModelSettings, ToolBinding } from '../types'
import { api, ApiError } from '../api'
import { EligibilityBuilder } from './EligibilityBuilder'
import { ListEditor } from './ListEditor'
import { KnowledgePicker } from './KnowledgePicker'
import { ToolsEditor } from './ToolsEditor'
import { ModelsEditor } from './ModelsEditor'
import { PipelineStrip } from './PipelineStrip'
import { resolve } from '../resolve'
import { Orb } from './Orb'
import { TopbarActions } from '../shell'
import { useOwner } from '../auth'
import { describeRule } from './LevelChip'

interface FormState {
  id: string
  name: string
  description: string
  system_prompt: string
  eligibility: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
  first_message: string
  llm_provider: string
  llm_model: string
  llm_temperature: number | null
  voice_id: string
  voice_stability: number | null
  voice_speed: number | null
  tts_provider: string
  tts_model: string
  stt_provider: string
  stt_model: string
  stt_language: string
}

function blank(id = ''): FormState {
  return {
    id,
    name: '',
    description: '',
    system_prompt: '',
    eligibility: '',
    triggers: [],
    tools: [],
    knowledge: [],
    first_message: '',
    llm_provider: '',
    llm_model: '',
    llm_temperature: null,
    voice_id: '',
    voice_stability: null,
    voice_speed: null,
    tts_provider: '',
    tts_model: '',
    stt_provider: '',
    stt_model: '',
    stt_language: '',
  }
}

function fromAgent(a: Agent): FormState {
  return {
    id: a.id,
    name: a.name,
    description: a.description,
    system_prompt: a.system_prompt,
    eligibility: a.eligibility,
    triggers: a.triggers,
    tools: a.tools,
    knowledge: a.knowledge,
    first_message: a.first_message,
    llm_provider: a.llm_provider,
    llm_model: a.llm_model,
    llm_temperature: a.llm_temperature,
    voice_id: a.voice_id,
    voice_stability: a.voice_stability,
    voice_speed: a.voice_speed,
    tts_provider: a.tts_provider ?? '',
    tts_model: a.tts_model ?? '',
    stt_provider: a.stt_provider ?? '',
    stt_model: a.stt_model ?? '',
    stt_language: a.stt_language ?? '',
  }
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Where a piece of the pipeline is set: a section id on this page. */
export type Section = 'prompt' | 'routing' | 'tools' | 'knowledge' | 'models'

interface Props {
  pid: string
  settings: ModelSettings
  catalog: Catalog | null
  mode: 'create' | 'edit'
  /** root -> ... -> this agent (edit) or -> the parent (create). */
  path?: Agent[]
  onSelectAgent?: (id: string) => void
  initial?: Agent
  parentId?: string | null
  parentName?: string
  availableTools: string[]
  onCancel: () => void
  onSaved: () => void
  onDeleted: () => void
}

export function AgentForm({
  pid,
  settings,
  catalog,
  mode,
  path = [],
  onSelectAgent,
  initial,
  parentId,
  parentName,
  availableTools,
  onCancel,
  onSaved,
  onDeleted,
}: Props) {
  const owner = useOwner()
  const start = () => (initial ? fromAgent(initial) : blank())
  const [state, setState] = useState<FormState>(start)
  const dirty = JSON.stringify(state) !== JSON.stringify(start())
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  const update = (patch: Partial<FormState>) => {
    setSavedAt(null)
    setState((s) => ({ ...s, ...patch }))
  }

  const save = async () => {
    if (saving) return
    setError(null)
    setSaving(true)
    try {
      const body = {
        name: state.name,
        description: state.description,
        system_prompt: state.system_prompt,
        eligibility: state.eligibility,
        triggers: state.triggers.filter((t) => t.trim() !== ''),
        tools: state.tools.filter((t) => t.id.trim() !== ''),
        knowledge: state.knowledge.filter((k) => k.trim() !== ''),
        first_message: state.first_message,
        llm_provider: state.llm_provider,
        llm_model: state.llm_model,
        llm_temperature: state.llm_temperature,
        voice_id: state.voice_id.trim(),
        voice_stability: state.voice_stability,
        voice_speed: state.voice_speed,
        tts_provider: state.tts_provider,
        tts_model: state.tts_model,
        stt_provider: state.stt_provider,
        stt_model: state.stt_model,
        stt_language: state.stt_language,
      }
      if (mode === 'create') await api.createAgent(pid, { ...body, id: state.id.trim(), parent_id: parentId ?? null })
      else if (initial) await api.updateAgent(pid, initial.id, body)
      setSavedAt(Date.now())
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  // ⌘S / Ctrl+S saves, like an editor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && owner) {
        e.preventDefault()
        if (dirty || mode === 'create') save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const remove = async () => {
    if (!initial) return
    if (!confirm(`Delete "${initial.name || initial.id}"? This can't be undone.`)) return
    setError(null)
    setDeleting(true)
    try {
      await api.deleteAgent(pid, initial.id)
      onDeleted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  const jump = (section: Section) => document.getElementById(`agent-${section}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const parent = mode === 'create' ? path.at(-1) : path.at(-2)
  const isRoot = mode === 'edit' && path.length <= 1
  const title = mode === 'create' ? 'New specialist' : initial?.name || initial?.id

  return (
    <form
      className="editor"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      {owner && (
        <TopbarActions>
          {(dirty || mode === 'create') && (
            <span className="topbar__note">{mode === 'create' ? 'Not created yet' : 'Unsaved changes'}</span>
          )}
          {savedAt && !dirty && <span className="topbar__note topbar__note--ok">Saved</span>}
          {mode === 'create' ? (
            <button type="button" className="btn-secondary" onClick={onCancel}>
              Cancel
            </button>
          ) : (
            dirty && (
              <button type="button" className="btn-secondary" onClick={() => setState(start())}>
                Discard
              </button>
            )
          )}
          <button
            type="button"
            className="btn-primary"
            onClick={save}
            disabled={saving || (mode === 'edit' && !dirty)}
            title="⌘S"
          >
            {saving ? 'Saving…' : mode === 'create' ? 'Create agent' : 'Save'}
          </button>
        </TopbarActions>
      )}

      <header className="editor__head">
        {path.length > (mode === 'create' ? 0 : 1) && (
          <nav className="editor__path" aria-label="Position in the workflow">
            {(mode === 'create' ? path : path.slice(0, -1)).map((a) => (
              <span key={a.id}>
                <button type="button" className="btn-link" onClick={() => onSelectAgent?.(a.id)}>
                  {a.name || a.id}
                </button>
                <span aria-hidden> / </span>
              </span>
            ))}
          </nav>
        )}
        <div className="editor__title">
          <Orb seed={`${pid}/${initial?.id ?? state.id ?? 'new'}`} size={34} />
          <h1>{title}</h1>
          {mode === 'edit' && initial && <code className="editor__id">{initial.id}</code>}
        </div>
        {mode === 'create' && <p className="editor__lede">Under {parentName ?? parentId}. It answers when the router hands it a turn.</p>}
        {mode === 'edit' && initial && <Facts agent={initial} />}
      </header>

      {error && <p className="error">{error}</p>}

      <PipelineStrip
        resolved={resolve(state, settings, catalog, isRoot)}
        toolCount={state.tools.filter((t) => t.id.trim()).length}
        specialists={mode === 'edit' && initial ? initial.children.length : 0}
        hasGate={mode === 'edit' && initial ? initial.children.some((c) => c.eligibility) : false}
        onOpen={(target) => jump(target === 'models' ? 'models' : target)}
      />

      <div className="editor__grid">
        <fieldset className="ro-fieldset editor__main" disabled={!owner}>
          {mode === 'create' && (
            <section className="editor__section">
              <div className="editor__row">
                <label className="field">
                  <span className="field__label">Name</span>
                  <input required value={state.name} onChange={(e) => update({ name: e.target.value })} placeholder="e.g. Bookings" />
                </label>
                <label className="field">
                  <span className="field__label">ID</span>
                  <input required value={state.id} onChange={(e) => update({ id: e.target.value })} placeholder="e.g. bookings" />
                </label>
              </div>
            </section>
          )}

          <section className="editor__section" id="agent-prompt">
            <div className="editor__label">
              <h2>System prompt</h2>
              <p>Who the agent is and how it talks. It writes every reply from this.</p>
            </div>
            <textarea
              className="editor__prompt"
              value={state.system_prompt}
              onChange={(e) => update({ system_prompt: e.target.value })}
              placeholder="You are the booking assistant of…"
              aria-label="System prompt"
            />
          </section>

          <section className="editor__section">
            <div className="editor__label">
              <h2>First message</h2>
              <p>What the agent says before the caller speaks. Leave it empty to wait for the caller.</p>
            </div>
            <textarea
              rows={2}
              value={state.first_message}
              onChange={(e) => update({ first_message: e.target.value })}
              placeholder={isRoot ? 'Buongiorno, come posso aiutarla?' : 'Usually empty for a specialist: it answers the turn it was handed.'}
              aria-label="First message"
            />
          </section>

          {mode === 'edit' && (
            <section className="editor__section">
              <div className="editor__label">
                <h2>Name and description</h2>
                <p>The router’s language model reads the description when keywords can’t decide.</p>
              </div>
              <label className="field">
                <span className="field__label">Name</span>
                <input required value={state.name} onChange={(e) => update({ name: e.target.value })} />
              </label>
              <label className="field">
                <span className="field__label">Description</span>
                <textarea rows={2} value={state.description} onChange={(e) => update({ description: e.target.value })} />
              </label>
            </section>
          )}
          {mode === 'create' && (
            <section className="editor__section">
              <div className="editor__label">
                <h2>Description</h2>
                <p>What this agent handles. The router’s language model reads it when keywords can’t decide.</p>
              </div>
              <textarea rows={2} value={state.description} onChange={(e) => update({ description: e.target.value })} aria-label="Description" />
            </section>
          )}

          <section className="editor__section" id="agent-routing">
            <div className="editor__label">
              <h2>How calls reach this agent</h2>
              <p>
                {isRoot
                  ? 'The receptionist answers first, so it needs no gate or keywords. Set them on its specialists.'
                  : `From ${parent?.name ?? 'its parent'}: the gate first, then the keywords. If neither settles it, the router’s model reads the description.`}
              </p>
            </div>
            {!isRoot && (
              <>
                <EligibilityBuilder value={state.eligibility} onChange={(eligibility) => update({ eligibility })} />
                <ListEditor
                  label="Keywords"
                  values={state.triggers}
                  placeholder="e.g. roaming"
                  onChange={(triggers) => update({ triggers })}
                />
              </>
            )}
          </section>

          <section className="editor__section" id="agent-tools">
            <div className="editor__label">
              <h2>Tools</h2>
              <p>Actions the agent can take before it replies: hand over to a human, end the call, a webhook, an MCP server.</p>
            </div>
            <ToolsEditor values={state.tools} availableTools={availableTools} onChange={(tools) => update({ tools })} />
          </section>

          <section className="editor__section" id="agent-knowledge">
            <div className="editor__label">
              <h2>Knowledge</h2>
              <p>Documents the agent searches with the knowledge tool. Manage them under Knowledge.</p>
            </div>
            <KnowledgePicker values={state.knowledge} onChange={(knowledge) => update({ knowledge })} />
          </section>

          {owner && mode === 'edit' && !isRoot && (
            <section className="editor__section editor__danger">
              <div className="editor__label">
                <h2>Delete this agent</h2>
                <p>Its specialists have to be moved or deleted first. Recorded calls are kept.</p>
              </div>
              <button type="button" className="btn-danger" onClick={remove} disabled={deleting}>
                {deleting ? 'Deleting…' : `Delete ${initial?.name || initial?.id}`}
              </button>
            </section>
          )}
        </fieldset>

        <aside className="editor__side" id="agent-models">
          <fieldset className="ro-fieldset" disabled={!owner}>
            <ModelsEditor
              mode="agent"
              compact
              value={state}
              project={settings}
              catalog={catalog}
              onChange={(patch) => update(patch as Partial<FormState>)}
            />
          </fieldset>
        </aside>
      </div>
    </form>
  )
}

function Facts({ agent }: { agent: Agent }) {
  const items: { text: string; gate?: boolean }[] = [
    agent.eligibility ? { text: `Gate: ${describeRule(agent.eligibility)}`, gate: true } : { text: 'Open to every caller' },
    { text: agent.triggers.length ? plural(agent.triggers.length, 'keyword') : 'No keywords' },
    { text: agent.tools.length ? plural(agent.tools.length, 'tool') : 'No tools' },
    { text: agent.knowledge.length ? plural(agent.knowledge.length, 'document') : 'No documents' },
  ]
  if (agent.children.length) items.push({ text: plural(agent.children.length, 'specialist') + ' below' })
  return (
    <ul className="editor__facts">
      {items.map((t) => (
        <li key={t.text} className={t.gate ? 'chip chip--gate' : 'chip'}>
          {t.text}
        </li>
      ))}
    </ul>
  )
}
