import { useEffect, useMemo, useState } from 'react'
import type { Agent, CallStats, TestRouteResult } from '../types'
import { api, ApiError } from '../api'
import { flatten } from '../tree'
import { describeRule, LEVELS } from './LevelChip'
import { EXAMPLES } from '../examples'
import { useTrees } from '../trees'

type Go = (view: 'call' | 'agents' | 'knowledge' | 'tools' | 'calls' | 'analytics') => void


const SECTIONS: { view: Parameters<Go>[0]; title: string; what: string }[] = [
  {
    view: 'agents',
    title: 'Agents',
    what: 'Create a single agent or a workflow, pick the speech, language and voice models, and see how each agent is built.',
  },
  { view: 'knowledge', title: 'Knowledge', what: 'Documents agents answer from, and a way to see which passages a question retrieves.' },
  { view: 'tools', title: 'Tools', what: 'Hand over to a human, end the call, call a webhook or an MCP server.' },
  { view: 'calls', title: 'Calls', what: 'Every call turn by turn, with the router level behind each decision and an evaluation.' },
  { view: 'analytics', title: 'Analytics', what: 'Volume, how often each router level decides, tool runs and evaluation results.' },
]

interface Step {
  key: 'gate_only' | 'pattern' | 'llm_fallback'
  state: 'decided' | 'passed' | 'skipped'
  text: React.ReactNode
}

/** The three levels for one routed utterance, in the order the router runs
 * them, each marked as the one that decided, one that ran without deciding,
 * or one that wasn't needed. */
function explain(result: TestRouteResult, utterance: string, root: Agent | null, simulated: boolean): Step[] {
  const children = root?.children ?? []
  const eligible = new Set(result.eligible_agents)
  const excluded = children.filter((c) => !eligible.has(c.id))
  const chosen = flatten(root).find((a) => a.id === result.agent_id)
  const chosenAgent = root ? findById(root, result.agent_id) : undefined
  const lowered = utterance.toLowerCase()
  const keyword = chosenAgent?.triggers.find((t) => lowered.includes(t.toLowerCase()))
  const name = chosen?.name || result.agent_id
  const stayed = !result.handed_off

  const gate: Step = {
    key: 'gate_only',
    state: result.resolved_by === 'gate_only' ? 'decided' : 'passed',
    text:
      excluded.length === 0 ? (
        <>All {children.length} specialists are open to this caller.</>
      ) : (
        <>
          {excluded.map((a, i) => (
            <span key={a.id}>
              {i > 0 && ', '}
              <s>{a.name}</s>
            </span>
          ))}{' '}
          {excluded.length === 1 ? 'is' : 'are'} closed to this caller: {excluded.map((a) => describeRule(a.eligibility)).join('; ')}.{' '}
          {result.eligible_agents.length} left to choose from.
        </>
      ),
  }
  const pattern: Step =
    result.resolved_by === 'pattern'
      ? {
          key: 'pattern',
          state: 'decided',
          text: keyword ? (
            <>
              <mark>{keyword}</mark> is a keyword of <strong>{name}</strong>.
            </>
          ) : (
            <>
              A keyword points to <strong>{name}</strong>.
            </>
          ),
        }
      : result.resolved_by === 'gate_only'
        ? { key: 'pattern', state: 'skipped', text: <>Not needed.</> }
        : { key: 'pattern', state: 'passed', text: <>No keyword points to a single open specialist.</> }
  const llm: Step =
    result.resolved_by === 'llm_fallback'
      ? {
          key: 'llm_fallback',
          state: 'decided',
          text: (
            <>
              {stayed ? (
                <>The receptionist keeps the call.</>
              ) : (
                <>
                  Hands the call to <strong>{name}</strong>.
                </>
              )}
              {simulated && <span className="ov-step__note"> Simulated here: no language model is configured.</span>}
            </>
          ),
        }
      : { key: 'llm_fallback', state: 'skipped', text: <>Not needed, so no model call.</> }
  return [gate, pattern, llm]
}

function findById(node: Agent, id: string): Agent | undefined {
  if (node.id === id) return node
  for (const c of node.children) {
    const hit = findById(c, id)
    if (hit) return hit
  }
  return undefined
}

function RouterDemo({ root }: { root: Agent | null }) {
  const [utterance, setUtterance] = useState(EXAMPLES[0].text)
  const [routed, setRouted] = useState<{ text: string; result: TestRouteResult } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const route = async (text: string) => {
    if (!text.trim()) return
    setUtterance(text)
    setBusy(true)
    setError(null)
    try {
      const result = await api.testRoute(text, null, 'voice', false)
      setRouted({ text, result })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const steps = routed ? explain(routed.result, routed.text, root, routed.result.provider === 'FakeProvider') : null
  const reply = routed?.result.reply.replace(/^\[[^\]]*\]\s*/, '')

  return (
    <section className="ov-demo" aria-labelledby="ov-demo-title">
      <h2 id="ov-demo-title">Route a caller</h2>
      <p className="ov-demo__lede">
        Pick something a caller might say, or type your own. The agents speak Italian; the router is the real one.
      </p>
      <form
        className="ov-demo__form"
        onSubmit={(e) => {
          e.preventDefault()
          route(utterance)
        }}
      >
        <input
          aria-label="What the caller says"
          value={utterance}
          onChange={(e) => setUtterance(e.target.value)}
          placeholder="Scrivi una frase in italiano"
        />
        <button type="submit" disabled={busy || !root}>
          {busy ? 'Routing…' : 'Route'}
        </button>
      </form>
      <div className="ov-demo__examples">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.text}
            type="button"
            className={routed?.text === ex.text ? 'ov-example ov-example--active' : 'ov-example'}
            onClick={() => route(ex.text)}
          >
            <span className="ov-example__it">{ex.text}</span>
            <span className="ov-example__en">{ex.gloss}</span>
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}

      {!routed && (
        <ol className="ov-steps ov-steps--idle" aria-hidden>
          {(['gate_only', 'pattern', 'llm_fallback'] as const).map((k, i) => (
            <li key={k} className={`ov-step ov-step--${k}`}>
              <span className="ov-step__level">
                <span className="ov-step__num">{i + 1}</span>
                {LEVELS[k].label}
              </span>
              <span className="ov-step__text">{LEVELS[k].what}</span>
              <span className="ov-step__state" />
            </li>
          ))}
        </ol>
      )}

      {steps && routed && (
        <div className="ov-result" key={routed.text + routed.result.agent_id}>
          <ol className="ov-steps">
            {steps.map((s, i) => (
              <li key={s.key} className={`ov-step ov-step--${s.state} ov-step--${s.key}`} style={{ animationDelay: `${i * 110}ms` }}>
                <span className="ov-step__level">
                  <span className="ov-step__num">{i + 1}</span>
                  {LEVELS[s.key].label}
                </span>
                <span className="ov-step__text">{s.text}</span>
                <span className="ov-step__state">
                  {s.state === 'decided' ? 'Decided' : s.state === 'passed' ? 'Passed on' : 'Skipped'}
                </span>
              </li>
            ))}
          </ol>
          <div className="ov-answer" style={{ animationDelay: '360ms' }}>
            <div className="ov-answer__who">
              {routed.result.agent_name} answers
              {routed.result.tool_ids_used.length > 0 && (
                <span className="ov-answer__tools">
                  {' '}
                  using{' '}
                  {routed.result.tool_ids_used.map((t, i) => (
                    <span key={t}>
                      {i > 0 && ', '}
                      <code>{t}</code>
                    </span>
                  ))}
                </span>
              )}
            </div>
            <p className="ov-answer__reply" lang="it">
              {reply}
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

function NoModelShare({ stats }: { stats: CallStats | null }) {
  if (!stats) return null
  const totals = stats.resolved_by_totals
  const all = Object.values(totals).reduce((a, b) => a + b, 0)
  if (all < 5) return null
  const cheap = (totals.gate_only ?? 0) + (totals.pattern ?? 0)
  const pct = Math.round((cheap / all) * 100)
  return (
    <p className="ov-stat">
      Across the {stats.total_calls} recorded calls here, <strong>{pct}%</strong> of routing decisions ({cheap} of {all})
      were made without calling a language model.
    </p>
  )
}

export function Overview({ go }: { root?: Agent | null; go: Go }) {
  // The landing page runs on the demo project.
  const root = useTrees(['demo']).demo ?? null
  const [stats, setStats] = useState<CallStats | null>(null)
  const count = useMemo(() => flatten(root).length, [root])

  useEffect(() => {
    api
      .getCallStats(true)
      .then(setStats)
      .catch(() => setStats(null))
  }, [])

  return (
    <div className="ov">
      <header className="ov-hero">
        <h1>
          One phone line, {count > 0 ? count : 'a family of'} agents, and a router that decides who answers.
        </h1>
        <p className="ov-hero__lede">
          Voice Orchestrator runs the customer line of a fictional Italian telecom. Every time the caller speaks, a
          three-level router picks the specialist for that turn, and only asks a language model when cheaper rules
          can't decide.
        </p>
        <div className="ov-hero__actions">
          <button type="button" className="btn-primary" onClick={() => go('call')}>
            Start a call
          </button>
          <button type="button" className="btn-secondary" onClick={() => go('agents')}>
            Explore the agents
          </button>
        </div>
      </header>

      <RouterDemo root={root} />

      <section className="ov-levels" aria-labelledby="ov-levels-title">
        <h2 id="ov-levels-title">How the router decides</h2>
        <ol className="ov-levels__list">
          <li className="ov-level ov-level--gate_only">
            <h3>Gate</h3>
            <p>
              Rules on what is known about the caller rule specialists in or out. Billing, for example, only opens to a
              verified caller. If one specialist is left, it gets the call.
            </p>
          </li>
          <li className="ov-level ov-level--pattern">
            <h3>Pattern</h3>
            <p>
              Each specialist has keywords. If exactly one open specialist matches what the caller said, it takes the
              turn. No model, no latency.
            </p>
          </li>
          <li className="ov-level ov-level--llm_fallback">
            <h3>LLM</h3>
            <p>
              Only when the first two can't settle it does a language model choose among the open specialists, or keep
              the call where it is.
            </p>
          </li>
        </ol>
        <NoModelShare stats={stats} />
      </section>

      <section className="ov-inside" aria-labelledby="ov-inside-title">
        <h2 id="ov-inside-title">What's inside</h2>
        <ul className="ov-inside__list">
          {SECTIONS.map((s) => (
            <li key={s.view}>
              <button type="button" className="ov-inside__link" onClick={() => go(s.view)}>
                {s.title}
              </button>
              <span>{s.what}</span>
            </li>
          ))}
        </ul>
      </section>

      <footer className="ov-foot">
        Built by Matteo Bigi with LiveKit, Deepgram and ElevenLabs.{' '}
        <a href="https://github.com/MattBi-web/voice-orchestrator" target="_blank" rel="noreferrer">
          Source on GitHub
        </a>
      </footer>
    </div>
  )
}
