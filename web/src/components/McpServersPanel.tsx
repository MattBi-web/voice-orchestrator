import { useEffect, useState } from 'react'
import type { McpServer } from '../types'
import { api, ApiError } from '../api'
import { ListEditor } from './ListEditor'
import { useOwner } from '../auth'

interface FormState {
  name: string
  command: string
  args: string[]
}

function blank(): FormState {
  return { name: '', command: '', args: [] }
}

function fromServer(s: McpServer): FormState {
  return { name: s.name, command: s.command, args: s.args }
}

function McpServerForm({
  mode,
  initial,
  onCancel,
  onSaved,
  onDeleted,
}: {
  mode: 'create' | 'edit'
  initial?: McpServer
  onCancel: () => void
  onSaved: () => void
  onDeleted: () => void
}) {
  const owner = useOwner()
  const [state, setState] = useState<FormState>(() => (initial ? fromServer(initial) : blank()))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const update = (patch: Partial<FormState>) => setState((s) => ({ ...s, ...patch }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const body: McpServer = {
        name: state.name.trim(),
        command: state.command.trim(),
        args: state.args.map((a) => a.trim()).filter((a) => a !== ''),
      }
      if (mode === 'create') {
        await api.createMcpServer(body)
      } else if (initial) {
        await api.updateMcpServer(initial.name, body)
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
    if (!confirm(`Delete MCP server "${initial.name}"? If an agent still uses "mcp:${initial.name}" this is blocked.`)) return
    setError(null)
    setDeleting(true)
    try {
      await api.deleteMcpServer(initial.name)
      onDeleted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <form className="agent-form mcp-panel__form" onSubmit={handleSubmit}>
      <fieldset className="ro-fieldset" disabled={!owner}>
      <h3>{mode === 'create' ? 'Nuovo server MCP' : `Modifica "${initial?.name}"`}</h3>
      {error && <p className="error">{error}</p>}

      <div className="field">
        <label>Nome</label>
        <input
          required
          disabled={mode === 'edit'}
          value={state.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="e.g. weather"
        />
      </div>

      <div className="field">
        <label>Comando</label>
        <input
          required
          value={state.command}
          onChange={(e) => update({ command: e.target.value })}
          placeholder="e.g. python3, oppure il path assoluto di un binario"
        />
      </div>

      <ListEditor
        label="Args"
        values={state.args}
        placeholder="e.g. -m my_mcp_server"
        onChange={(args) => update({ args })}
      />

      </fieldset>
      <div className="form-actions">
        {owner && (
          <button type="submit" disabled={saving}>
            {saving ? 'Salvataggio…' : 'Salva'}
          </button>
        )}
        <button type="button" className="btn-secondary" onClick={onCancel}>
          {owner ? 'Annulla' : 'Chiudi'}
        </button>
        {owner && mode === 'edit' && (
          <button type="button" className="btn-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Elimino…' : 'Elimina'}
          </button>
        )}
      </div>
    </form>
  )
}

type Selection = { kind: 'none' } | { kind: 'edit'; name: string } | { kind: 'create' }

interface Props {
  // Called after any create/update/delete so App.tsx can refresh
  // GET /api/tools — a server added here must show up as "mcp:<name>" in
  // ToolsEditor's dropdown immediately, with no reload of the page.
  onChanged: () => void
}

export function McpServersPanel({ onChanged }: Props) {
  const owner = useOwner()
  const [servers, setServers] = useState<McpServer[]>([])
  const [selection, setSelection] = useState<Selection>({ kind: 'none' })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    api
      .listMcpServers()
      .then((r) => {
        setServers(r.servers)
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

  const editing = selection.kind === 'edit' ? servers.find((s) => s.name === selection.name) : undefined

  return (
    <section className="mcp-panel">
      <div className="mcp-panel__header">
        <h2>Server MCP</h2>
        {owner && selection.kind === 'none' && (
          <button type="button" className="btn-link" onClick={() => setSelection({ kind: 'create' })}>
            + nuovo server
          </button>
        )}
      </div>
      <p className="mcp-panel__hint">
        Ogni tool <code>mcp:&lt;nome&gt;</code> che vedi nell'editor dei tool qui sopra viene da uno di questi
        server, lanciato come processo locale al momento in cui serve. <strong>Nota di sicurezza:</strong> comando
        e argomenti che scrivi qui vengono eseguiti per davvero sulle macchine su cui girano il backend e il worker
        vocale. Per questo, quando è impostata una password, solo il proprietario può aggiungerli o modificarli.
      </p>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className="mcp-panel__table-wrap">
          <table className="dashboard__table">
            <thead>
              <tr>
                <th>Tool id</th>
                <th>Comando</th>
                <th>Args</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {servers.map((s) => (
                <tr key={s.name}>
                  <td>
                    <code>mcp:{s.name}</code>
                  </td>
                  <td>
                    <code>{s.command}</code>
                  </td>
                  <td>
                    <code>{s.args.join(' ')}</code>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => setSelection({ kind: 'edit', name: s.name })}
                    >
                      modifica
                    </button>
                  </td>
                </tr>
              ))}
              {servers.length === 0 && (
                <tr>
                  <td colSpan={4} className="dashboard__empty">
                    Nessun server MCP configurato.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {selection.kind === 'create' && (
        <McpServerForm
          mode="create"
          onCancel={() => setSelection({ kind: 'none' })}
          onSaved={handleChanged}
          onDeleted={handleChanged}
        />
      )}
      {selection.kind === 'edit' && editing && (
        <McpServerForm
          mode="edit"
          initial={editing}
          onCancel={() => setSelection({ kind: 'none' })}
          onSaved={handleChanged}
          onDeleted={handleChanged}
        />
      )}
    </section>
  )
}
