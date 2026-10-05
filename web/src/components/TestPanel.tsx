import { useEffect, useRef, useState } from 'react'
import type { Agent, CallEvent, LlmStatus } from '../types'
import { api, ApiError } from '../api'
import { flatten } from '../tree'
import { useOwner } from '../auth'
import { EXAMPLES } from '../examples'
import { CallTimeline } from './CallTimeline'

interface Props {
  root: Agent | null
}

/** The agent page's test panel (blocco 7, fase B): a text conversation with
 * the family, several turns long, on the real router (POST
 * /api/test/conversations). Each turn is explained the same way as on the
 * call page. The conversation is created on the first message and recorded
 * in Calls when it ends. */
export function TestPanel({ root }: Props) {
  const owner = useOwner()
  const [llm, setLlm] = useState<LlmStatus | null>(null)
  const [useModel, setUseModel] = useState(false)
  const [startId, setStartId] = useState('')
  const [channel, setChannel] = useState('voice')
  const [verified, setVerified] = useState(false)
  const [convId, setConvId] = useState<string | null>(null)
  const [events, setEvents] = useState<CallEvent[]>([])
  const [simulated, setSimulated] = useState(true)
  const [text, setText] = useState('')
  const [sending, setSending] = useState<string | null>(null)
  // The verified switch is sent only when it changes, so a tool that sets
  // `authenticated` itself mid-conversation isn't overwritten every turn.
  const sentVerified = useRef<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const convRef = useRef<string | null>(null)
  convRef.current = convId

  useEffect(() => {
    api
      .getLlmStatus()
      .then((s) => {
        setLlm(s)
        setUseModel(s.real && owner)
      })
      .catch(() => setLlm(null))
    // Leaving the page ends the conversation, so it is recorded.
    return () => {
      if (convRef.current) api.endConversation(convRef.current).catch(() => undefined)
    }
  }, [])

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [events, busy])

  const ended = events.some((e) => e.type === 'ended')

  const reset = () => {
    if (convId) api.endConversation(convId).catch(() => undefined)
    setConvId(null)
    setEvents([])
    setError(null)
  }

  // Changing who answers first, the channel or the model starts over.
  const resetOn =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v)
      reset()
    }

  const send = async (utterance: string) => {
    const said = utterance.trim()
    if (!said || busy || ended) return
    setBusy(true)
    setError(null)
    setText('')
    setSending(said)
    try {
      let id = convId
      if (!id) {
        const started = await api.startConversation(startId || null, channel, useModel)
        id = started.id
        setConvId(id)
        setSimulated(started.simulated)
        setEvents(started.greeting ? [started.greeting] : [])
        sentVerified.current = null
      }
      const slots = verified !== (sentVerified.current ?? false) ? { authenticated: verified } : {}
      const turn = await api.conversationTurn(id, said, slots)
      sentVerified.current = verified
      setEvents((prev) => [...prev, turn, ...(turn.ended ? [{ type: 'ended', reason: 'end_call' } as CallEvent] : [])])
      if (turn.ended) setConvId(null)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404 && convId) {
        setConvId(null)
        setError('This conversation expired. Send again to start a new one.')
      } else {
        setError(err instanceof ApiError ? err.message : String(err))
      }
      setText(said)
    } finally {
      setBusy(false)
      setSending(null)
    }
  }

  const flat = flatten(root)

  return (
    <section className="tp" aria-labelledby="tp-title">
      <header className="tp__head">
        <h2 id="tp-title">Try it</h2>
        {(events.length > 0 || convId) && (
          <button type="button" className="btn-link" onClick={reset}>
            New conversation
          </button>
        )}
      </header>

      <div className="tp__opts">
        <label>
          <span>Start with</span>
          <select value={startId} onChange={(e) => resetOn(setStartId)(e.target.value)}>
            {flat.map((a) => (
              <option key={a.id} value={a.depth === 0 ? '' : a.id}>
                {'  '.repeat(a.depth)}
                {a.name || a.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Channel</span>
          <select value={channel} onChange={(e) => resetOn(setChannel)(e.target.value)}>
            <option value="voice">Voice</option>
            <option value="chat">Chat</option>
          </select>
        </label>
        <label className="tp__check" title="Sets authenticated = true, which the gate checks (Billing opens only to verified callers)">
          <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
          Verified caller
        </label>
        {owner && llm?.real && (
          <label className="tp__check">
            <input type="checkbox" checked={useModel} onChange={(e) => resetOn(setUseModel)(e.target.checked)} />
            Reply with <code>{llm.resolved}</code>
          </label>
        )}
      </div>

      <div className="tp__body" ref={bodyRef}>
        {events.length === 0 && !sending ? (
          <div className="tp__empty">
            <p>Write as the caller, in Italian. The router is the real one; the conversation keeps going until you say goodbye.</p>
            <div className="tp__examples">
              {EXAMPLES.map((ex) => (
                <button key={ex.text} type="button" className="ov-example" onClick={() => send(ex.text)} disabled={busy || !root}>
                  <span className="ov-example__it">{ex.text}</span>
                  <span className="ov-example__en">{ex.gloss}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <CallTimeline events={events} callerLabel="You" pending={sending} compact />
        )}
      </div>

      {error && <p className="error tp__error">{error}</p>}

      {ended ? (
        <div className="tp__ended">
          <button type="button" className="btn-secondary" onClick={reset}>
            Start a new conversation
          </button>
        </div>
      ) : (
        <form
          className="tp__input"
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
        >
          <input
            aria-label="What the caller says"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={events.length ? 'Reply…' : 'e.g. il wifi non si connette'}
            disabled={!root}
          />
          <button type="submit" className="btn-primary" disabled={busy || !text.trim() || !root}>
            {busy ? '…' : 'Send'}
          </button>
        </form>
      )}
      <p className="tp__fine">
        {events.length > 0 && !simulated
          ? 'Replies come from the configured model.'
          : llm?.real && !owner
            ? 'Replies are placeholders in the public demo; routing and tools are real.'
            : 'Replies are placeholders (no language model); routing and tools are real.'}
      </p>
    </section>
  )
}
