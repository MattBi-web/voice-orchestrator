import { useEffect, useMemo, useState } from 'react'
import type { Agent, CallStats, Project, TestRouteResult } from '../types'
import { api, ApiError } from '../api'
import { flatten } from '../tree'
import { describeRule, LEVELS } from './LevelChip'
import { EXAMPLES } from '../examples'
import { useTrees } from '../trees'
import { Orb } from './Orb'
import { Icon } from './Icon'
import { useOwner } from '../auth'

type Go = (view: 'call' | 'agents' | 'knowledge' | 'tools' | 'calls' | 'analytics') => void



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

export function Overview({ go, projects = [] }: { go: Go; projects?: Project[] }) {
  // The landing page's router demo runs on the demo project.
  const root = useTrees(['demo']).demo ?? null
  const [stats, setStats] = useState<CallStats | null>(null)
  const count = useMemo(() => flatten(root).length, [root])
  const owner = useOwner()

  useEffect(() => {
    api
      .getCallStats(true)
      .then(setStats)
      .catch(() => setStats(null))
  }, [])

  const totals = stats?.resolved_by_totals ?? {}
  const decisions = Object.values(totals).reduce((a, b) => a + b, 0)
  const cheap = (totals.gate_only ?? 0) + (totals.pattern ?? 0)

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
            <Icon name="phone" />
            Start a call
          </button>
          <button type="button" className="btn-secondary" onClick={() => go('agents')}>
            Explore the demo agent
          </button>
          {owner && (
            <a className="btn-secondary" href="#/new-agent">
              <Icon name="plus" />
              New agent
            </a>
          )}
        </div>
      </header>

      <div className="kpis">
        <div className="kpi">
          <span>Agents</span>
          <strong>{projects.length || '—'}</strong>
        </div>
        <div className="kpi">
          <span>Calls and tests</span>
          <strong>{stats ? stats.total_calls : '—'}</strong>
        </div>
        <div className="kpi">
          <span>Average length</span>
          <strong>{stats ? `${stats.avg_duration_seconds.toFixed(0)} s` : '—'}</strong>
        </div>
        <div className="kpi">
          <span>Decided without a model</span>
          <strong>{decisions ? `${Math.round((cheap / decisions) * 100)}%` : '—'}</strong>
        </div>
      </div>

      {projects.length > 0 && (
        <section className="ov-jump" aria-labelledby="ov-jump-title">
          <h2 id="ov-jump-title">Jump back in</h2>
          <ul className="cards">
            {projects.slice(0, 6).map((p) => (
              <li key={p.id}>
                <a className="card" href={`#/agents/${encodeURIComponent(p.id)}/agent`}>
                  <Orb seed={p.id} size={30} />
                  <span>
                    <strong>{p.name}</strong>
                    <small>
                      {p.kind === 'single' ? 'Single agent' : `Workflow, ${p.agent_count} agents`},{' '}
                      {p.call_count ? `${p.call_count} call${p.call_count === 1 ? '' : 's'}` : 'no calls yet'}
                    </small>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

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
