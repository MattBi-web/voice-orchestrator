import { useEffect, useState, type ReactNode } from 'react'
import type { Agent, Catalog, ModelSettings, ToolBinding } from '../types'
import { api, ApiError } from '../api'
import { EligibilityBuilder } from './EligibilityBuilder'
import { ListEditor } from './ListEditor'
import { KnowledgePicker } from './KnowledgePicker'
import { ToolsEditor } from './ToolsEditor'
import { ModelsEditor } from './ModelsEditor'
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

type Tab = 'behavior' | 'routing' | 'models' | 'tools' | 'knowledge'

const TABS: { id: Tab; label: string }[] = [
  { id: 'behavior', label: 'Behavior' },
  { id: 'routing', label: 'Routing' },
  { id: 'models', label: 'Models' },
  { id: 'tools', label: 'Tools' },
  { id: 'knowledge', label: 'Knowledge' },
]

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** The agent at a glance, under its name: what the router checks, what it
 * can do, and where it sits. */
function Summary({ agent }: { agent: Agent }): ReactNode {
  const items: string[] = [
    agent.eligibility ? `Gate: ${describeRule(agent.eligibility)}` : 'Open to every caller',
    agent.triggers.length ? plural(agent.triggers.length, 'keyword') : 'No keywords',
    agent.tools.length ? plural(agent.tools.length, 'tool') : 'No tools',
    agent.knowledge.length ? plural(agent.knowledge.length, 'document') : 'No documents',
  ]
  if (agent.children.length) items.push(plural(agent.children.length, 'specialist') + ' below')
  return (
    <ul className="agent-head__facts">
      {items.map((t) => (
        <li key={t} className={t.startsWith('Gate') ? 'agent-head__fact agent-head__fact--gate' : 'agent-head__fact'}>
          {t}
        </li>
      ))}
    </ul>
  )
}

export type AgentTab = Tab
export type AgentDraft = FormState

interface Props {
  pid: string
  tab?: Tab
  onTab?: (tab: Tab) => void
  /** Called with the form's current values, saved or not. */
  onDraft?: (draft: FormState) => void
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
  tab: controlledTab,
  onTab,
  onDraft,
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
  const [ownTab, setOwnTab] = useState<Tab>('behavior')
  // The project page can drive the tab (its pipeline opens the right one).
  const tab = controlledTab ?? ownTab
  const setTab = (t: Tab) => (onTab ? onTab(t) : setOwnTab(t))
  useEffect(() => {
    onDraft?.(state)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])
  const dirty = JSON.stringify(state) !== JSON.stringify(start())
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const update = (patch: Partial<FormState>) => setState((s) => ({ ...s, ...patch }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const voiceId = state.voice_id.trim()
      const models = {
        tts_provider: state.tts_provider,
        tts_model: state.tts_model,
        stt_provider: state.stt_provider,
        stt_model: state.stt_model,
        stt_language: state.stt_language,
      }
      if (mode === 'create') {
        await api.createAgent(pid, {
          ...models,
          id: state.id.trim(),
          parent_id: parentId ?? null,
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
          voice_id: voiceId,
          voice_stability: state.voice_stability,
          voice_speed: state.voice_speed,
        })
      } else if (initial) {
        await api.updateAgent(pid, initial.id, {
          ...models,
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
          voice_id: voiceId,
          voice_stability: state.voice_stability,
          voice_speed: state.voice_speed,
        })
      }
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!initial) return
    if (!confirm(`Delete agent "${initial.id}"? This can't be undone.`)) return
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

  const crumbs = mode === 'edit' ? path.slice(0, -1) : path
  const title = mode === 'create' ? `New specialist under ${parentName ?? parentId}` : initial?.name || initial?.id

  return (
    <form className="agent-form" onSubmit={handleSubmit}>
      <header className="agent-head">
        {crumbs.length > 0 && (
          <nav className="agent-head__path" aria-label="Position in the family">
            {crumbs.map((a) => (
              <span key={a.id}>
                <button type="button" className="btn-link" onClick={() => onSelectAgent?.(a.id)}>
                  {a.name || a.id}
                </button>
                <span aria-hidden> / </span>
              </span>
            ))}
          </nav>
        )}
        <h2>
          {title}
          {mode === 'edit' && initial && <code className="agent-head__id">{initial.id}</code>}
        </h2>
        {mode === 'edit' && initial && initial.description && <p className="agent-head__desc">{initial.description}</p>}
        {mode === 'edit' && initial && <Summary agent={initial} />}
      </header>



      <div className="agent-tabs" role="tablist" aria-label="Agent settings">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? 'agent-tab agent-tab--active' : 'agent-tab'}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}

      <fieldset className="ro-fieldset agent-panels" disabled={!owner}>
        <div role="tabpanel" hidden={tab !== 'behavior'}>
          {mode === 'create' && (
            <div className="field">
              <label>ID</label>
              <input required value={state.id} onChange={(e) => update({ id: e.target.value })} placeholder="e.g. vip_support" />
            </div>
          )}
          <div className="field">
            <label>Name</label>
            <input required value={state.name} onChange={(e) => update({ name: e.target.value })} />
          </div>
          <div className="field">
            <label>Description</label>
            <textarea
              rows={2}
              value={state.description}
              onChange={(e) => update({ description: e.target.value })}
              placeholder="What this agent handles. The router reads it when keywords are not enough."
            />
          </div>
          <div className="field">
            <label>System prompt</label>
            <textarea rows={6} value={state.system_prompt} onChange={(e) => update({ system_prompt: e.target.value })} />
          </div>
          <div className="field">
            <label>First message</label>
            <textarea
              rows={2}
              value={state.first_message}
              onChange={(e) => update({ first_message: e.target.value })}
              placeholder="What this agent says before the caller speaks. Leave empty to stay silent."
            />
          </div>
        </div>

        <div role="tabpanel" hidden={tab !== 'routing'}>
          <p className="agent-panels__lede">
            How the router reaches this agent from {mode === 'create' ? parentName ?? parentId : crumbs.at(-1)?.name ?? 'the line'}: the gate
            first, then the keywords. If neither settles it, a model reads the description.
          </p>
          <EligibilityBuilder value={state.eligibility} onChange={(eligibility) => update({ eligibility })} />
          <ListEditor
            label="Keywords that route the call here"
            values={state.triggers}
            placeholder="e.g. roaming"
            onChange={(triggers) => update({ triggers })}
          />
        </div>

        <div role="tabpanel" hidden={tab !== 'models'}>
          <p className="agent-panels__lede">
            Each piece uses the project’s model unless you override it here. The voice and the speech-to-text switch when
            the call reaches this agent.
          </p>
          <ModelsEditor mode="agent" value={state} project={settings} catalog={catalog} onChange={(patch) => update(patch as Partial<FormState>)} />
        </div>

        <div role="tabpanel" hidden={tab !== 'tools'}>
          <ToolsEditor values={state.tools} availableTools={availableTools} onChange={(tools) => update({ tools })} />
        </div>

        <div role="tabpanel" hidden={tab !== 'knowledge'}>
          <KnowledgePicker values={state.knowledge} onChange={(knowledge) => update({ knowledge })} />
        </div>
      </fieldset>

      {owner && (
        <div className={dirty || mode === 'create' ? 'form-actions form-actions--dirty' : 'form-actions'}>
          <button type="submit" disabled={saving || (mode === 'edit' && !dirty)}>
            {saving ? 'Saving…' : mode === 'create' ? 'Create agent' : 'Save changes'}
          </button>
          {mode === 'create' ? (
            <button type="button" className="btn-secondary" onClick={onCancel}>
              Cancel
            </button>
          ) : (
            dirty && (
              <button type="button" className="btn-secondary" onClick={() => setState(start())}>
                Discard changes
              </button>
            )
          )}
          {dirty && mode === 'edit' && <span className="form-actions__note">Unsaved changes</span>}
          {mode === 'edit' && (
            <button type="button" className="btn-danger" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Deleting…' : 'Delete agent'}
            </button>
          )}
        </div>
      )}
    </form>
  )
}
