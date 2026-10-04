import { useState } from 'react'
import type { Agent, ToolBinding } from '../types'
import { api, ApiError } from '../api'
import { ListEditor } from './ListEditor'
import { ToolsEditor } from './ToolsEditor'

interface FormState {
  id: string
  name: string
  description: string
  system_prompt: string
  eligibility: string
  voice: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
}

function blank(id = ''): FormState {
  return {
    id,
    name: '',
    description: '',
    system_prompt: '',
    eligibility: '',
    voice: 'default',
    triggers: [],
    tools: [],
    knowledge: [],
  }
}

function fromAgent(a: Agent): FormState {
  return {
    id: a.id,
    name: a.name,
    description: a.description,
    system_prompt: a.system_prompt,
    eligibility: a.eligibility,
    voice: a.voice,
    triggers: a.triggers,
    tools: a.tools,
    knowledge: a.knowledge,
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
      if (mode === 'create') {
        await api.createAgent({
          id: state.id.trim(),
          parent_id: parentId ?? null,
          name: state.name,
          description: state.description,
          system_prompt: state.system_prompt,
          eligibility: state.eligibility,
          voice: state.voice,
          triggers: state.triggers.filter((t) => t.trim() !== ''),
          tools: state.tools.filter((t) => t.id.trim() !== ''),
          knowledge: state.knowledge.filter((k) => k.trim() !== ''),
        })
      } else if (initial) {
        await api.updateAgent(initial.id, {
          name: state.name,
          description: state.description,
          system_prompt: state.system_prompt,
          eligibility: state.eligibility,
          voice: state.voice,
          triggers: state.triggers.filter((t) => t.trim() !== ''),
          tools: state.tools.filter((t) => t.id.trim() !== ''),
          knowledge: state.knowledge.filter((k) => k.trim() !== ''),
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
      <h2>{mode === 'create' ? `New agent under "${parentName ?? parentId}"` : `Edit "${initial?.id}"`}</h2>
      {error && <p className="error">{error}</p>}

      {mode === 'create' && (
        <div className="field">
          <label>Id</label>
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
          placeholder="Shown to the LLM-fallback classifier when routing is ambiguous"
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

      <div className="field">
        <label>Eligibility (Level-1 gate expression)</label>
        <input
          value={state.eligibility}
          onChange={(e) => update({ eligibility: e.target.value })}
          placeholder="e.g. authenticated == true"
        />
      </div>

      <div className="field">
        <label>Voice</label>
        <input value={state.voice} onChange={(e) => update({ voice: e.target.value })} />
      </div>

      <ListEditor
        label="Triggers (Level-2 keywords)"
        values={state.triggers}
        placeholder="e.g. roaming"
        onChange={(triggers) => update({ triggers })}
      />

      <ToolsEditor values={state.tools} availableTools={availableTools} onChange={(tools) => update({ tools })} />

      <ListEditor
        label="Knowledge files"
        values={state.knowledge}
        placeholder="e.g. internet_support.md"
        onChange={(knowledge) => update({ knowledge })}
      />

      <div className="form-actions">
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        {mode === 'edit' && (
          <button type="button" className="btn-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        )}
      </div>
    </form>
  )
}
