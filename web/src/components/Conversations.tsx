import { useEffect, useState } from 'react'
import type { CallRecord } from '../types'
import { api, ApiError } from '../api'
import { ConversationDetail } from './ConversationDetail'
import { AnalysisConfigEditor } from './AnalysisConfigEditor'
import { VerdictChip } from './VerdictChip'

type SubView = 'calls' | 'criteria'

interface Props {
  selectedCallId: string | null
  onSelectCall: (callId: string | null) => void
}

export function Conversations({ selectedCallId, onSelectCall }: Props) {
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
        <h2>Conversazioni</h2>
        <div className="convos__subtabs">
          <button
            type="button"
            className={sub === 'calls' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setSub('calls')}
          >
            Chiamate
          </button>
          <button
            type="button"
            className={sub === 'criteria' ? 'app__tab app__tab--active' : 'app__tab'}
            onClick={() => setSub('criteria')}
          >
            Criteri di valutazione
          </button>
          {sub === 'calls' && (
            <button type="button" className="btn-secondary" onClick={load}>
              Aggiorna
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
          Nessuna chiamata registrata. Prova il box "try it" nell'Agent builder, una sessione <code>chat</code> da CLI o
          una chiamata dalla tab "Test live (voce)".
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
                    <span className={`dashboard__badge dashboard__badge--${c.source}`}>{c.source}</span>
                    <span className="convos__item-time">{new Date(c.started_at).toLocaleString('it-IT')}</span>
                  </span>
                  <span className="convos__item-agent">{c.final_agent_id ?? '—'}</span>
                  <VerdictChip verdict={c.call_successful} />
                </button>
              </li>
            ))}
          </ul>
          <div className="convos__detail">
            {selectedCallId ? (
              <ConversationDetail callId={selectedCallId} onAnalyzed={load} />
            ) : (
              <p className="app__hint">Seleziona una chiamata a sinistra per vederne trascrizione e analisi.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
