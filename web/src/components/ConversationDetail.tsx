import { useEffect, useState } from 'react'
import type { CallDetail } from '../types'
import { api, ApiError } from '../api'
import { VerdictChip } from './VerdictChip'

const LEVEL_LABELS: Record<string, string> = {
  gate_only: 'solo gate',
  pattern: 'pattern',
  llm_fallback: 'LLM fallback',
}

function formatValue(value: string | number | boolean | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'sì' : 'no'
  return String(value)
}

export function ConversationDetail({ callId, onAnalyzed }: { callId: string; onAnalyzed: () => void }) {
  const [call, setCall] = useState<CallDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)

  useEffect(() => {
    setCall(null)
    setError(null)
    api
      .getCall(callId)
      .then(setCall)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [callId])

  const runAnalysis = async () => {
    setAnalyzing(true)
    setError(null)
    try {
      const analysis = await api.analyzeCall(callId)
      setCall((c) => (c ? { ...c, analysis } : c))
      onAnalyzed()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setAnalyzing(false)
    }
  }

  if (error && !call) return <p className="error">{error}</p>
  if (!call) return <p>Loading…</p>

  const analysis = call.analysis

  return (
    <div className="convo-detail">
      <div className="convo-detail__meta">
        <span className={`dashboard__badge dashboard__badge--${call.source}`}>{call.source}</span>
        <span>{new Date(call.started_at).toLocaleString('it-IT')}</span>
        <span>{call.duration_seconds.toFixed(1)}s</span>
        <span>canale: {call.channel}</span>
        <span>agente finale: {call.final_agent_id ?? '—'}</span>
        <span>handoff: {call.handoffs}</span>
        <code className="convo-detail__id">{call.call_id}</code>
      </div>

      {error && <p className="error">{error}</p>}

      <section className="convo-detail__section">
        <h3>Trascrizione</h3>
        {call.turns.length === 0 ? (
          <p className="dashboard__empty">
            Nessuna trascrizione: questa chiamata è stata registrata prima che le trascrizioni venissero salvate.
          </p>
        ) : (
          <ol className="transcript">
            {call.turns.map((t, i) => (
              <li key={i} className={`transcript__turn transcript__turn--${t.speaker}`}>
                <div className="transcript__who">
                  {t.speaker === 'caller' ? 'Chiamante' : t.agent_id ?? 'agente'}
                </div>
                <div className="transcript__bubble">{t.text}</div>
                {t.routing && (
                  <div className="transcript__trace" title={t.routing.reason}>
                    → <strong>{t.routing.chosen_agent ?? '—'}</strong> · {LEVEL_LABELS[t.routing.resolved_by] ?? t.routing.resolved_by}
                    {' · '}
                    {t.routing.latency_ms.toFixed(1)} ms · candidati: {t.routing.eligible_agents.join(', ') || '—'}
                    {t.handoff && (
                      <span className="transcript__handoff">
                        {' '}
                        · handoff {t.handoff.from_agent} → {t.handoff.to_agent}
                      </span>
                    )}
                  </div>
                )}
                {t.tools && t.tools.length > 0 && (
                  <div className="transcript__tools">
                    {t.tools.map((tool, j) => (
                      <code key={j} className="transcript__tool">
                        {tool}
                      </code>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="convo-detail__section">
        <div className="convo-detail__analysis-head">
          <h3>Analisi</h3>
          <button type="button" className="btn-secondary" onClick={runAnalysis} disabled={analyzing}>
            {analyzing ? 'Analizzo…' : analysis ? 'Rianalizza' : 'Analizza'}
          </button>
        </div>

        {!analysis ? (
          <p className="dashboard__empty">
            Non ancora analizzata. L'analisi usa i criteri della scheda "Criteri di valutazione".
          </p>
        ) : (
          <>
            <div className="convo-detail__verdict">
              <VerdictChip verdict={analysis.call_successful} />
              <span className={`method-badge method-badge--${analysis.method}`}>
                {analysis.method === 'llm' ? `LLM · ${analysis.provider}` : 'euristica, non un giudizio LLM'}
              </span>
              <span className="convo-detail__when">{new Date(analysis.analyzed_at).toLocaleString('it-IT')}</span>
            </div>
            {analysis.method === 'heuristic' && (
              <p className="convo-detail__note">
                Nessun provider LLM configurato: i risultati sotto vengono da un confronto di parole chiave, utile a
                provare il flusso ma non a valutare la chiamata. Imposta <code>VOICE_ORCH_PROVIDER</code> (e la chiave
                relativa) sul backend per un giudizio vero.
              </p>
            )}
            {analysis.summary && <p className="convo-detail__summary">{analysis.summary}</p>}

            <h4>Criteri</h4>
            <table className="dashboard__table convo-detail__table">
              <tbody>
                {analysis.criteria.map((c) => (
                  <tr key={c.criterion_id}>
                    <td>
                      <code>{c.criterion_id}</code>
                    </td>
                    <td>
                      <VerdictChip verdict={c.result} />
                    </td>
                    <td className="convo-detail__rationale">{c.rationale}</td>
                  </tr>
                ))}
                {analysis.criteria.length === 0 && (
                  <tr>
                    <td colSpan={3} className="dashboard__empty">
                      Nessun criterio configurato.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>

            <h4>Dati estratti</h4>
            <table className="dashboard__table convo-detail__table">
              <tbody>
                {analysis.data.map((d) => (
                  <tr key={d.item_id}>
                    <td>
                      <code>{d.item_id}</code>
                    </td>
                    <td className="convo-detail__value">{formatValue(d.value)}</td>
                    <td className="convo-detail__rationale">{d.rationale}</td>
                  </tr>
                ))}
                {analysis.data.length === 0 && (
                  <tr>
                    <td colSpan={3} className="dashboard__empty">
                      Nessun campo configurato.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  )
}
