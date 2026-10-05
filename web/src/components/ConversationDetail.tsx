import { useEffect, useState } from 'react'
import type { Agent, CallDetail } from '../types'
import { api, ApiError } from '../api'
import { VerdictChip } from './VerdictChip'
import { SOURCE_LABELS, formatWhen } from './LevelChip'
import { CallTimeline, transcriptToEvents } from './CallTimeline'
import { findAgent } from '../tree'
import { useOwner } from '../auth'

function formatValue(value: string | number | boolean | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

export function ConversationDetail({
  callId,
  root,
  onAnalyzed,
}: {
  callId: string
  root: Agent | null
  onAnalyzed: () => void
}) {
  const owner = useOwner()
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
        <span className={`dashboard__badge dashboard__badge--${call.source}`}>{SOURCE_LABELS[call.source] ?? call.source}</span>
        <span>{formatWhen(call.started_at)}</span>
        <span>{call.duration_seconds.toFixed(1)}s</span>
        <span>{call.channel === 'voice' ? 'Voice' : call.channel === 'chat' ? 'Chat' : call.channel}</span>
        <span>
          ended with {call.final_agent_id ? findAgent(root, call.final_agent_id)?.name || call.final_agent_id : '—'}
        </span>
        <span>{call.handoffs} handover{call.handoffs === 1 ? '' : 's'}</span>
        <code className="convo-detail__id">{call.call_id}</code>
      </div>

      {error && <p className="error">{error}</p>}

      <section className="convo-detail__section">
        <h3>Transcript</h3>
        {call.turns.length === 0 ? (
          <p className="dashboard__empty">
            No transcript: this call was recorded before transcripts were saved.
          </p>
        ) : (
          <CallTimeline events={transcriptToEvents(call.turns, root)} callerLabel="Caller" />
        )}
      </section>

      <section className="convo-detail__section">
        <div className="convo-detail__analysis-head">
          <h3>Evaluation</h3>
          <button
            type="button"
            className="btn-secondary"
            onClick={runAnalysis}
            disabled={analyzing || !owner}
            title={owner ? undefined : 'Sign in as the owner to evaluate calls'}
          >
            {analyzing ? 'Evaluating…' : analysis ? 'Evaluate again' : 'Evaluate'}
          </button>
        </div>

        {!analysis ? (
          <p className="dashboard__empty">
            Not evaluated yet. Evaluation checks the call against the criteria under Calls → Criteria.
          </p>
        ) : (
          <>
            <div className="convo-detail__verdict">
              <VerdictChip verdict={analysis.call_successful} />
              <span className={`method-badge method-badge--${analysis.method}`}>
                {analysis.method === 'llm' ? `LLM · ${analysis.provider}` : 'rule-based, no model'}
              </span>
              <span className="convo-detail__when">Evaluated {formatWhen(analysis.analyzed_at)}</span>
            </div>
            {analysis.method === 'heuristic' && (
              <p className="convo-detail__note">
                No language model is configured, so only structural criteria (final agent, tools used) get a verdict.
                Criteria written in plain language stay unclear until a model is set up.
              </p>
            )}
            {analysis.summary && <p className="convo-detail__summary">{analysis.summary}</p>}

            <h4>Criteria</h4>
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
                      No criteria configured.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>

            <h4>Extracted data</h4>
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
                      No fields configured.
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
