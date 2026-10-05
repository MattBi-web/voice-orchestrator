import { useEffect, useState } from 'react'
import type { Agent, CallRecord } from '../types'
import { findAgent } from '../tree'
import { api, ApiError } from '../api'
import { ConversationDetail } from './ConversationDetail'
import { AnalysisConfigEditor } from './AnalysisConfigEditor'
import { VerdictChip } from './VerdictChip'
import { SOURCE_LABELS, formatWhen } from './LevelChip'

type SubView = 'calls' | 'criteria'

interface Props {
  root: Agent | null
  selectedCallId: string | null
  onSelectCall: (callId: string | null) => void
}

export function Conversations({ root, selectedCallId, onSelectCall }: Props) {
  const [sub, setSub] = useState<SubView>('calls')
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    api
      .getCalls(200)
      .then((r) => {
        setCalls(r.calls)
        setError(null)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

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
                  <span className="convos__item-agent">
                    {c.final_agent_id ? findAgent(root, c.final_agent_id)?.name || c.final_agent_id : '—'}
                    <span className="convos__item-turns">
                      {' '}
                      · {c.turn_count} message{c.turn_count === 1 ? '' : 's'}
                    </span>
                  </span>
                  <VerdictChip verdict={c.call_successful} />
                </button>
              </li>
            ))}
          </ul>
          <div className="convos__detail">
            {selectedCallId ? (
              <ConversationDetail callId={selectedCallId} root={root} onAnalyzed={load} />
            ) : (
              <p className="app__hint">Select a call to see its transcript and evaluation.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
