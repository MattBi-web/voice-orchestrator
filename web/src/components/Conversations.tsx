import { useEffect, useState } from 'react'
import type { CallRecord } from '../types'
import { useProjects, useTrees } from '../trees'
import { findAgent } from '../tree'
import { api, ApiError } from '../api'
import { ConversationDetail } from './ConversationDetail'
import { AnalysisConfigEditor } from './AnalysisConfigEditor'
import { VerdictChip } from './VerdictChip'
import { SOURCE_LABELS, formatWhen } from './LevelChip'

type SubView = 'calls' | 'criteria'

interface Props {
  /** Blocco 8: only this project's calls; omitted = every project, with a
   * project filter. */
  project?: string
  selectedCallId: string | null
  onSelectCall: (callId: string | null) => void
}

export function Conversations({ project, selectedCallId, onSelectCall }: Props) {
  const [filter, setFilter] = useState('')
  const scope = project ?? filter
  const projects = useProjects()
  const [sub, setSub] = useState<SubView>('calls')
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    api
      .getCalls(200, scope)
      .then((r) => {
        setCalls(r.calls)
        setError(null)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope])

  const treesByProject = useTrees(calls.map((c) => c.project_id))
  const projectName = (pid: string) => projects.find((p) => p.id === pid)?.name ?? pid
  const selected = calls.find((c) => c.call_id === selectedCallId)

  return (
    <div className="convos">
      <div className="dashboard__toolbar">
        <div className="convos__subtabs">
          <button
            type="button"
            className={sub === 'calls' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setSub('calls')}
          >
            Calls
          </button>
          <button
            type="button"
            className={sub === 'criteria' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setSub('criteria')}
          >
            Criteria
          </button>
          {sub === 'calls' && project === undefined && projects.length > 1 && (
            <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Agent">
              <option value="">All agents</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          {sub === 'calls' && (
            <button type="button" className="btn-secondary" onClick={load}>
              Refresh
            </button>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {sub === 'criteria' ? (
        <AnalysisConfigEditor />
      ) : loading ? (
        <p>Loading…</p>
      ) : calls.length === 0 ? (
        <p className="dashboard__empty">
          No calls yet. Start a call, or send a message from the text test under Agents.
        </p>
      ) : (
        <div className="convos__layout">
          <ul className="convos__list">
            {calls.map((c) => (
              <li key={c.call_id}>
                <button
                  type="button"
                  className={c.call_id === selectedCallId ? 'convos__item convos__item--active' : 'convos__item'}
                  onClick={() => onSelectCall(c.call_id)}
                >
                  <span className="convos__item-top">
                    <span className={`dashboard__badge dashboard__badge--${c.source}`}>{SOURCE_LABELS[c.source] ?? c.source}</span>
                    <span className="convos__item-time">{formatWhen(c.started_at)}</span>
                  </span>
                  {project === undefined && <span className="convos__item-project">{projectName(c.project_id)}</span>}
                  <span className="convos__item-agent">
                    {c.final_agent_id ? findAgent(treesByProject[c.project_id] ?? null, c.final_agent_id)?.name || c.final_agent_id : '—'}
                    <span className="convos__item-turns">
                      {' '}
                      {c.turn_count} message{c.turn_count === 1 ? '' : 's'}
                    </span>
                  </span>
                  <VerdictChip verdict={c.call_successful} />
                </button>
              </li>
            ))}
          </ul>
          <div className="convos__detail">
            {selectedCallId ? (
              <ConversationDetail
                callId={selectedCallId}
                root={selected ? (treesByProject[selected.project_id] ?? null) : null}
                onAnalyzed={load}
              />
            ) : (
              <p className="app__hint">Select a call to see its transcript and evaluation.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
