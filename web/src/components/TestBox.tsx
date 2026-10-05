import { useEffect, useState } from 'react'
import type { Agent, LlmStatus, TestRouteResult } from '../types'
import { api, ApiError } from '../api'
import { flatten } from '../tree'
import { LevelChip } from './LevelChip'
import { useOwner } from '../auth'

interface Props {
  root: Agent | null
}

/** The minimal "try it" console: type an utterance, optionally force a
 * starting agent (otherwise the real router starts from the tree's root,
 * exactly like a fresh call would), and see the actual orchestrator.handle_turn()
 * decision — not a simulation of it. Wired straight to POST /api/test/route. */
export function TestBox({ root }: Props) {
  const owner = useOwner()
  const [utterance, setUtterance] = useState('')
  const [startAgentId, setStartAgentId] = useState<string>('')
  const [channel, setChannel] = useState('voice')
  const [result, setResult] = useState<TestRouteResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [llm, setLlm] = useState<LlmStatus | null>(null)
  // D3: default to the real model whenever one is configured — the try-it
  // box should show the replies a real call gets, not FakeProvider's echo.
  const [useConfigured, setUseConfigured] = useState(false)

  useEffect(() => {
    api
      .getLlmStatus()
      .then((s) => {
        setLlm(s)
        setUseConfigured(s.real && owner)
      })
      .catch(() => setLlm(null))
  }, [])

  const flat = flatten(root)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!utterance.trim()) return
    setError(null)
    setLoading(true)
    setResult(null)
    try {
      const res = await api.testRoute(utterance, startAgentId || null, channel, useConfigured)
      setResult(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="test-box">
      <h2>Test with text</h2>
      <p className="section-lede">Type what a caller might say and see which agent answers, why, and with which tools.</p>
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label>Caller says</label>
          <textarea
            rows={2}
            required
            value={utterance}
            onChange={(e) => setUtterance(e.target.value)}
            placeholder="e.g. quanto costa il roaming in Francia? (the demo agents speak Italian)"
          />
        </div>
        <div className="test-box__row">
          <div className="field">
            <label>Start from agent</label>
            <select value={startAgentId} onChange={(e) => setStartAgentId(e.target.value)}>
              <option value="">Receptionist (start of the call)</option>
              {flat.map((a) => (
                <option key={a.id} value={a.id}>
                  {'—'.repeat(a.depth)} {a.name || a.id}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Channel</label>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="voice">voice</option>
              <option value="chat">chat</option>
            </select>
          </div>
        </div>
        <label className="test-box__provider">
          <input
            type="checkbox"
            checked={useConfigured}
            disabled={!llm?.real || !owner}
            onChange={(e) => setUseConfigured(e.target.checked)}
          />
          {llm?.real ? (
            <>
              Reply with the configured model (<code>{llm.resolved}</code>)
            </>
          ) : llm && llm.requested !== 'fake' ? (
            <>
              The configured model ({llm.requested}) isn't reachable, so replies are simulated. Routing is real.
            </>
          ) : (
            <>
              Replies are simulated (no language model configured). Routing and tools are real.
            </>
          )}
        </label>
        <button type="submit" disabled={loading || !root}>
          {loading ? 'Routing…' : 'Send'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="test-result">
          <dl>
            <dt>Answered by</dt>
            <dd>
              {result.agent_name} <code>{result.agent_id}</code>
            </dd>
            <dt>Decided by</dt>
            <dd>
              <LevelChip level={result.resolved_by} />
            </dd>
            <dt>Candidates</dt>
            <dd>{result.eligible_agents.join(', ') || '—'}</dd>
            <dt>Handed over</dt>
            <dd>{result.handed_off ? 'yes' : 'no'}</dd>
            <dt>Tools used</dt>
            <dd>{result.tool_ids_used.join(', ') || '—'}</dd>
            <dt>Reply from</dt>
            <dd>{result.provider === 'FakeProvider' ? 'Simulated (no model)' : <code>{result.provider}</code>}</dd>
            <dt>Reply</dt>
            <dd className="test-result__reply">{result.reply}</dd>
          </dl>
        </div>
      )}
    </div>
  )
}
