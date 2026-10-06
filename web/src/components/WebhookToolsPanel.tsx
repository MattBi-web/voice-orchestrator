import { useEffect, useRef, useState } from 'react'
import type { WebhookExecution, WebhookMethod, WebhookParam, WebhookTool } from '../types'
import { api, ApiError } from '../api'
import { KeyValueEditor } from './KeyValueEditor'
import { ListEditor } from './ListEditor'
import { WebhookParamsEditor } from './WebhookParamsEditor'
import { useOwner } from '../auth'
import { formatWhen } from './LevelChip'

interface FormState {
  name: string
  description: string
  url: string
  method: WebhookMethod
  headers: Record<string, string>
  params: WebhookParam[]
  triggers: string[]
  timeout_seconds: number
}

const METHODS: WebhookMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

function blank(): FormState {
  return { name: '', description: '', url: '', method: 'POST', headers: {}, params: [], triggers: [], timeout_seconds: 5 }
}

function fromTool(t: WebhookTool): FormState {
  return {
    name: t.name,
    description: t.description,
    url: t.url,
    method: t.method,
    headers: t.headers,
    params: t.params,
    triggers: t.triggers,
    timeout_seconds: t.timeout_seconds,
  }
}

function WebhookToolForm({
  mode,
  initial,
  onCancel,
  onSaved,
  onDeleted,
}: {
  mode: 'create' | 'edit'
  initial?: WebhookTool
  onCancel: () => void
  onSaved: () => void
  onDeleted: () => void
}) {
  const owner = useOwner()
  const [state, setState] = useState<FormState>(() => (initial ? fromTool(initial) : blank()))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const update = (patch: Partial<FormState>) => setState((s) => ({ ...s, ...patch }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const body: WebhookTool = {
        name: state.name.trim(),
        description: state.description.trim(),
        url: state.url.trim(),
        method: state.method,
        headers: Object.fromEntries(
          Object.entries(state.headers).filter(([k]) => k.trim() !== '').map(([k, v]) => [k.trim(), v]),
        ),
        params: state.params.filter((p) => p.name.trim() !== '').map((p) => ({ ...p, name: p.name.trim() })),
        triggers: state.triggers.map((t) => t.trim()).filter((t) => t !== ''),
        timeout_seconds: state.timeout_seconds,
      }
      if (mode === 'create') {
        await api.createWebhookTool(body)
      } else if (initial) {
        await api.updateWebhookTool(initial.name, body)
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
    if (!confirm(`Delete the webhook "${initial.name}"? It can't be deleted while an agent still uses "webhook:${initial.name}".`)) return
    setError(null)
    setDeleting(true)
    try {
      await api.deleteWebhookTool(initial.name)
      onDeleted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <form className="agent-form webhook-panel__form" onSubmit={handleSubmit}>
      <fieldset className="ro-fieldset" disabled={!owner}>
      <h3>{mode === 'create' ? 'New webhook' : `Webhook "${initial?.name}"`}</h3>
      {error && <p className="error">{error}</p>}

      <div className="field">
        <label>Name</label>
        <input
          required
          disabled={mode === 'edit'}
          value={state.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="e.g. order_status"
        />
      </div>

      <div className="field">
        <label>Description</label>
        <input
          value={state.description}
          onChange={(e) => update({ description: e.target.value })}
          placeholder="What it does, briefly"
        />
      </div>

      <div className="field">
        <label>URL</label>
        <input
          required
          value={state.url}
          onChange={(e) => update({ url: e.target.value })}
          placeholder="https://api.example.com/orders"
        />
      </div>

      <div className="field">
        <label>Method</label>
        <select value={state.method} onChange={(e) => update({ method: e.target.value as WebhookMethod })}>
          {METHODS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Timeout (seconds)</label>
        <input
          type="number"
          min={1}
          max={30}
          step={1}
          value={state.timeout_seconds}
          onChange={(e) => update({ timeout_seconds: Number(e.target.value) || 5 })}
        />
      </div>

      <KeyValueEditor
        label="Headers"
        values={state.headers}
        keyPlaceholder="e.g. Authorization"
        valuePlaceholder="e.g. Bearer … or {{secret:NAME}}"
        hint={
          'Write {{secret:NAME}} to read the value from the VOICE_ORCH_SECRET_NAME environment variable on the ' +
          'server. Secrets are never stored or shown here.'
        }
        onChange={(headers) => update({ headers })}
      />

      <WebhookParamsEditor values={state.params} onChange={(params) => update({ params })} />

      <ListEditor
        label="Runs when the caller says"
        values={state.triggers}
        placeholder="e.g. stato della rete"
        onChange={(triggers) => update({ triggers })}
      />

      </fieldset>
      <div className="form-actions">
        {owner && (
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save webhook'}
          </button>
        )}
        <button type="button" className="btn-secondary" onClick={onCancel}>
          {owner ? 'Cancel' : 'Close'}
        </button>
        {owner && mode === 'edit' && (
          <button type="button" className="btn-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete webhook'}
          </button>
        )}
      </div>
    </form>
  )
}

function ExecutionsLog() {
  const [executions, setExecutions] = useState<WebhookExecution[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    api
      .listWebhookExecutions(50)
      .then((r) => {
        setExecutions(r.executions)
        setError(null)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="webhook-panel__executions">
      <div className="mcp-panel__header">
        <h3>Recent runs</h3>
        <button type="button" className="btn-link" onClick={load}>
          Refresh
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className="mcp-panel__table-wrap">
          <table className="dashboard__table">
            <thead>
              <tr>
                <th>When</th>
                <th>Webhook</th>
                <th>Agent</th>
                <th>Method</th>
                <th>Result</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((e, i) => (
                <tr key={i}>
                  <td>{formatWhen(e.at)}</td>
                  <td>
                    <code>webhook:{e.tool_name}</code>
                  </td>
                  <td>{e.agent_id}</td>
                  <td>{e.method}</td>
                  <td>
                    <span className={`verdict verdict--${e.ok ? 'success' : 'failure'}`}>
                      <span className="verdict__icon">{e.ok ? '✓' : '✕'}</span>
                      {e.status_code ?? (e.error || 'error')}
                    </span>
                  </td>
                  <td>{Math.round(e.latency_ms)} ms</td>
                </tr>
              ))}
              {executions.length === 0 && (
                <tr>
                  <td colSpan={6} className="dashboard__empty">
                    No runs yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

type Selection = { kind: 'none' } | { kind: 'edit'; name: string } | { kind: 'create' }

interface Props {
  // Called after any create/update/delete so App.tsx can refresh GET
  // /api/tools — a tool added here must show up as "webhook:<name>" in
  // ToolsEditor's dropdown immediately, with no reload of the page.
  onChanged: () => void
  /** Bumped by the Tools page's "Add …" tile: open the create form here. */
  createSignal?: number
}

export function WebhookToolsPanel({ onChanged, createSignal = 0 }: Props) {
  const panelRef = useRef<HTMLElement | null>(null)
  const owner = useOwner()
  const [tools, setTools] = useState<WebhookTool[]>([])
  const [selection, setSelection] = useState<Selection>({ kind: 'none' })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!createSignal) return
    setSelection({ kind: 'create' })
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [createSignal])

  const load = () => {
    api
      .listWebhookTools()
      .then((r) => {
        setTools(r.tools)
        setError(null)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const handleChanged = () => {
    setSelection({ kind: 'none' })
    load()
    onChanged()
  }

  const editing = selection.kind === 'edit' ? tools.find((t) => t.name === selection.name) : undefined

  return (
    <section className="mcp-panel webhook-panel" ref={panelRef}>
      <div className="mcp-panel__header">
        <h2>Webhooks</h2>
        {owner && selection.kind === 'none' && (
          <button type="button" className="btn-link" onClick={() => setSelection({ kind: 'create' })}>
            + Add webhook
          </button>
        )}
      </div>
      <p className="mcp-panel__hint">
        Each webhook adds a tool named <code>webhook:&lt;name&gt;</code> that calls an HTTP endpoint when the caller
        says one of its trigger phrases. Parameters come from the call or are fixed here.
      </p>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className="mcp-panel__table-wrap">
          <table className="dashboard__table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Method</th>
                <th>URL</th>
                <th>Triggers</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tools.map((t) => (
                <tr key={t.name}>
                  <td>
                    <code>webhook:{t.name}</code>
                  </td>
                  <td>{t.method}</td>
                  <td>
                    <code>{t.url}</code>
                  </td>
                  <td>{t.triggers.join(', ')}</td>
                  <td>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => setSelection({ kind: 'edit', name: t.name })}
                    >
                      {owner ? 'Edit' : 'View'}
                    </button>
                  </td>
                </tr>
              ))}
              {tools.length === 0 && (
                <tr>
                  <td colSpan={5} className="dashboard__empty">
                    No webhooks yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {selection.kind === 'create' && (
        <WebhookToolForm
          mode="create"
          onCancel={() => setSelection({ kind: 'none' })}
          onSaved={handleChanged}
          onDeleted={handleChanged}
        />
      )}
      {selection.kind === 'edit' && editing && (
        <WebhookToolForm
          mode="edit"
          initial={editing}
          onCancel={() => setSelection({ kind: 'none' })}
          onSaved={handleChanged}
          onDeleted={handleChanged}
        />
      )}

      <ExecutionsLog />
    </section>
  )
}
