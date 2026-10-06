import { useEffect, useRef, useState } from 'react'
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
      <h3>{mode === 'create' ? 'New MCP server' : `MCP server "${initial?.name}"`}</h3>
      {error && <p className="error">{error}</p>}

      <div className="field">
        <label>Name</label>
        <input
          required
          disabled={mode === 'edit'}
          value={state.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="e.g. weather"
        />
      </div>

      <div className="field">
        <label>Command</label>
        <input
          required
          value={state.command}
          onChange={(e) => update({ command: e.target.value })}
          placeholder="e.g. python3, or an absolute path to a binary"
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
            {saving ? 'Saving…' : 'Save server'}
          </button>
        )}
        <button type="button" className="btn-secondary" onClick={onCancel}>
          {owner ? 'Cancel' : 'Close'}
        </button>
        {owner && mode === 'edit' && (
          <button type="button" className="btn-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete server'}
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
  /** Bumped by the Tools page's "Add …" tile: open the create form here. */
  createSignal?: number
}

export function McpServersPanel({ onChanged, createSignal = 0 }: Props) {
  const panelRef = useRef<HTMLElement | null>(null)
  const owner = useOwner()
  const [servers, setServers] = useState<McpServer[]>([])
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
    <section className="mcp-panel" ref={panelRef}>
      <div className="mcp-panel__header">
        <h2>MCP servers</h2>
        {owner && selection.kind === 'none' && (
          <button type="button" className="btn-link" onClick={() => setSelection({ kind: 'create' })}>
            + Add server
          </button>
        )}
      </div>
      <p className="mcp-panel__hint">
        Each server adds a tool named <code>mcp:&lt;name&gt;</code>. The command runs as a process on the servers
        that host this app, which is why only the owner can add or change one.
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
                <th>Command</th>
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
                      {owner ? 'Edit' : 'View'}
                    </button>
                  </td>
                </tr>
              ))}
              {servers.length === 0 && (
                <tr>
                  <td colSpan={4} className="dashboard__empty">
                    No MCP servers yet.
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
