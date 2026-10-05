import type { ReactNode } from 'react'
import type { Agent, CallEvent, TranscriptTurn } from '../types'
import { describeRule, LevelChip } from './LevelChip'
import { GLOSSES } from '../examples'

/** The explained call timeline (blocco 7): caller and agent bubbles, and
 * under each caller line a strip in the router level's color saying why that
 * agent answered. Built from call_events.py events, so the call page (live,
 * from the LiveKit data channel) and the agent page's text test (from
 * /api/test/conversations) render a turn the same way. */

type TurnEvent = Extract<CallEvent, { type: 'turn' }>

const stripSpeaker = (reply: string) => reply.replace(/^\[[^\]]*\]\s*/, '')

/** Why the router gave this turn to this agent, in one or two sentences. */
function explainTurn(ev: TurnEvent): ReactNode {
  const closed =
    ev.excluded.length > 0 ? (
      <>
        {ev.excluded.map((a, i) => (
          <span key={a.id}>
            {i > 0 && ', '}
            <s>{a.name}</s>
          </span>
        ))}{' '}
        closed: {ev.excluded.map((a) => describeRule(a.rule)).join('; ')}.{' '}
      </>
    ) : null
  let decision: ReactNode
  if (ev.resolved_by === 'pattern') {
    decision = ev.keyword ? (
      <>
        <mark>{ev.keyword}</mark> is a keyword of <strong>{ev.agent_name}</strong>.
      </>
    ) : (
      <>
        A keyword points to <strong>{ev.agent_name}</strong>.
      </>
    )
  } else if (ev.resolved_by === 'gate_only') {
    decision =
      ev.eligible.length === 0 ? (
        <>
          <strong>{ev.from_agent_name}</strong> has no specialists below it, so it keeps the call.
        </>
      ) : (
        <>
          Only <strong>{ev.agent_name}</strong> is open to this caller.
        </>
      )
  } else {
    decision = (
      <>
        No single keyword match, so the model{' '}
        {ev.handed_off ? (
          <>
            handed the call to <strong>{ev.agent_name}</strong>.
          </>
        ) : (
          <>
            kept the call with <strong>{ev.agent_name}</strong>.
          </>
        )}
        {ev.simulated && (
          <span className="call-route__note"> Simulated: no language model is used here, so the reply is a placeholder.</span>
        )}
      </>
    )
  }
  return (
    <>
      {closed}
      {decision}
    </>
  )
}

export function CallTimeline({
  events,
  callerLabel,
  pending,
  endedByYou = false,
  glossed = false,
  compact = false,
}: {
  events: CallEvent[]
  callerLabel: string
  pending?: string | null
  endedByYou?: boolean
  glossed?: boolean
  compact?: boolean
}) {
  const items: ReactNode[] = []
  events.forEach((ev, i) => {
    if (ev.type === 'greeting') {
      items.push(
        <li key={`g${i}`} className="call-msg call-msg--agent">
          <span className="call-msg__who">{ev.agent_name}</span>
          <p lang="it">{ev.text}</p>
        </li>,
      )
    } else if (ev.type === 'turn') {
      items.push(
        <li key={`c${ev.seq}`} className="call-msg call-msg--caller">
          <span className="call-msg__who">{callerLabel}</span>
          <p lang="it">{ev.caller}</p>
          {glossed && GLOSSES[ev.caller] && <span className="call-msg__gloss">{GLOSSES[ev.caller]}</span>}
        </li>,
        <li key={`r${ev.seq}`} className={`call-route call-route--${ev.resolved_by}`}>
          <LevelChip level={ev.resolved_by} />
          <span className="call-route__text">{explainTurn(ev)}</span>
          {ev.latency_ms != null && <span className="call-route__ms">{ev.latency_ms.toFixed(1)} ms</span>}
        </li>,
      )
      if (ev.handed_off) {
        items.push(
          <li key={`h${ev.seq}`} className="call-mark">
            Handed over: {ev.from_agent_name} → <strong>{ev.agent_name}</strong>
          </li>,
        )
      }
      items.push(
        <li key={`a${ev.seq}`} className="call-msg call-msg--agent">
          <span className="call-msg__who">
            {ev.agent_name}
            {ev.tools.map((t) => (
              <code key={t} className="call-tool">
                {t}
              </code>
            ))}
          </span>
          <p lang="it">{stripSpeaker(ev.reply)}</p>
        </li>,
      )
    } else {
      items.push(
        <li key={`e${i}`} className="call-mark call-mark--end">
          {ev.reason === 'end_call' ? 'The agent ended the call (end_call tool)' : 'Call ended'}
        </li>,
      )
    }
  })
  if (pending) {
    items.push(
      <li key="pending" className="call-msg call-msg--caller call-msg--pending">
        <span className="call-msg__who">{callerLabel}</span>
        <p lang="it">{pending}</p>
      </li>,
    )
  }
  if (endedByYou && !events.some((e) => e.type === 'ended')) {
    items.push(
      <li key="hangup" className="call-mark call-mark--end">
        You hung up
      </li>,
    )
  }
  return <ol className={compact ? 'call-timeline call-timeline--compact' : 'call-timeline'}>{items}</ol>
}

/** A recorded call's transcript (GET /api/calls/{id}) as timeline events, so
 * the Calls page explains a past turn the way the call page does live. The
 * record stores the routing decision but not the gate rules or the keyword,
 * so those come from the family as it is now (`root`); a keyword is shown
 * only if it actually appears in what the caller said. */
export function transcriptToEvents(turns: TranscriptTurn[], root: Agent | null): CallEvent[] {
  const byId = new Map<string, Agent>()
  const index = (a: Agent) => {
    byId.set(a.id, a)
    a.children.forEach(index)
  }
  if (root) index(root)
  const name = (id: string | null | undefined) => (id ? byId.get(id)?.name || id : 'Agent')

  const events: CallEvent[] = []
  let current = root?.id ?? null
  let open: TurnEvent | null = null
  let seq = 0
  for (const t of turns) {
    if (t.speaker === 'caller') {
      if (open) events.push(open)
      const r = t.routing
      const from = t.handoff?.from_agent ?? current
      const chosen = r?.chosen_agent ?? t.handoff?.to_agent ?? current
      const eligible = r?.eligible_agents ?? []
      const children = (from && byId.get(from)?.children) || []
      const chosenAgent = chosen ? byId.get(chosen) : undefined
      const lowered = t.text.toLowerCase()
      seq += 1
      open = {
        type: 'turn',
        seq,
        caller: t.text,
        from_agent_id: from ?? '',
        from_agent_name: name(from),
        agent_id: chosen ?? '',
        agent_name: name(chosen),
        resolved_by: r?.resolved_by ?? 'gate_only',
        eligible,
        excluded: r ? children.filter((c) => !eligible.includes(c.id)).map((c) => ({ id: c.id, name: c.name, rule: c.eligibility })) : [],
        keyword:
          r?.resolved_by === 'pattern' ? (chosenAgent?.triggers.find((k) => lowered.includes(k.toLowerCase())) ?? null) : null,
        handed_off: Boolean(t.handoff),
        tools: [],
        reply: '',
        latency_ms: r?.latency_ms ?? null,
        simulated: false,
      }
      current = chosen
    } else if (open) {
      open.reply = t.text
      open.tools = t.tools ?? []
      if (t.agent_id) {
        open.agent_id = t.agent_id
        open.agent_name = name(t.agent_id)
        current = t.agent_id
      }
      events.push(open)
      open = null
    } else {
      events.push({ type: 'greeting', agent_id: t.agent_id ?? '', agent_name: name(t.agent_id), text: t.text })
    }
  }
  if (open) events.push(open)
  return events
}
