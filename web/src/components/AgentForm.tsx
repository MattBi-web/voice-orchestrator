import { useState } from 'react'
import type { Agent, ToolBinding } from '../types'
import { api, ApiError } from '../api'
import { EligibilityBuilder } from './EligibilityBuilder'
import { ListEditor } from './ListEditor'
import { KnowledgePicker } from './KnowledgePicker'
import { LlmOverridePicker } from './LlmOverridePicker'
import { ToolsEditor } from './ToolsEditor'
import { VoicePicker } from './VoicePicker'
import { useOwner } from '../auth'

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
  }
}

interface Props {
  mode: 'create' | 'edit'
  initial?: Agent
  parentId?: string | null
  parentName?: string
  availableTools: string[]
  onCancel: () => void
  onSaved: () => void
  onDeleted: () => void
}

export function AgentForm({ mode, initial, parentId, parentName, availableTools, onCancel, onSaved, onDeleted }: Props) {
  const owner = useOwner()
  const [state, setState] = useState<FormState>(() => (initial ? fromAgent(initial) : blank()))
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
      if (mode === 'create') {
        await api.createAgent({
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
          llm_temperature: state.llm_provider ? state.llm_temperature : null,
          voice_id: voiceId,
          voice_stability: voiceId ? state.voice_stability : null,
          voice_speed: voiceId ? state.voice_speed : null,
        })
      } else if (initial) {
        await api.updateAgent(initial.id, {
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
          llm_temperature: state.llm_provider ? state.llm_temperature : null,
          voice_id: voiceId,
          voice_stability: voiceId ? state.voice_stability : null,
          voice_speed: voiceId ? state.voice_speed : null,
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
      await api.deleteAgent(initial.id)
      onDeleted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <form className="agent-form" onSubmit={handleSubmit}>
      <fieldset className="ro-fieldset" disabled={!owner}>
      <h2>
        {mode === 'create'
          ? `New specialist under ${parentName ?? parentId}`
          : owner
            ? initial?.name || initial?.id
            : initial?.name || initial?.id}
      </h2>
      {error && <p className="error">{error}</p>}

      {mode === 'create' && (
        <div className="field">
          <label>ID</label>
          <input
            required
            value={state.id}
            onChange={(e) => update({ id: e.target.value })}
            placeholder="e.g. vip_support"
          />
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
        <textarea
          rows={4}
          value={state.system_prompt}
          onChange={(e) => update({ system_prompt: e.target.value })}
        />
      </div>

      <EligibilityBuilder value={state.eligibility} onChange={(eligibility) => update({ eligibility })} />

      <div className="field">
        <label>First message</label>
        <textarea
          rows={2}
          value={state.first_message}
          onChange={(e) => update({ first_message: e.target.value })}
          placeholder="What this agent says before the caller speaks. Leave empty to stay silent."
        />
      </div>

      <LlmOverridePicker
        value={{
          llm_provider: state.llm_provider,
          llm_model: state.llm_model,
          llm_temperature: state.llm_temperature,
        }}
        onChange={(v) => update(v)}
      />

      <VoicePicker
        value={{
          voice_id: state.voice_id,
          voice_stability: state.voice_stability,
          voice_speed: state.voice_speed,
        }}
        onChange={(v) => update(v)}
      />

      <ListEditor
        label="Keywords that route the call here"
        values={state.triggers}
        placeholder="e.g. roaming"
        onChange={(triggers) => update({ triggers })}
      />

      <ToolsEditor values={state.tools} availableTools={availableTools} onChange={(tools) => update({ tools })} />

      <KnowledgePicker values={state.knowledge} onChange={(knowledge) => update({ knowledge })} />

      </fieldset>
      <div className="form-actions">
        {owner && (
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : mode === 'create' ? 'Create agent' : 'Save changes'}
          </button>
        )}
        <button type="button" className="btn-secondary" onClick={onCancel}>
          {owner ? 'Cancel' : 'Close'}
        </button>
        {owner && mode === 'edit' && (
          <button type="button" className="btn-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete agent'}
          </button>
        )}
      </div>
    </form>
  )
}
