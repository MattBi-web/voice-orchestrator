import type { Resolved } from '../resolve'

export type PipelineTarget = 'models' | 'routing' | 'tools'

interface Props {
  resolved: Resolved[]
  toolCount: number
  specialists: number
  hasGate: boolean
  onOpen: (target: PipelineTarget) => void
}

const SOURCE: Record<Resolved['source'], string> = {
  agent: 'Override',
  project: 'Project default',
  deployment: 'Server default',
}

/** How this agent is built, in the order a turn goes through it (blocco 8):
 * what the caller says is transcribed, the router decides who answers, the
 * language model writes the reply (with tools), and the voice speaks it.
 * Each piece shows the model it will actually use and where that choice
 * comes from; clicking one opens the tab where it's set. */
export function PipelineStrip({ resolved, toolCount, specialists, hasGate, onOpen }: Props) {
  const by = Object.fromEntries(resolved.map((r) => [r.piece, r])) as Record<Resolved['piece'], Resolved>
  const blocks: { key: string; title: string; target: PipelineTarget; body: React.ReactNode; source?: Resolved['source'] }[] = [
    {
      key: 'stt',
      title: 'Speech to text',
      target: 'models',
      source: by.stt.source,
      body: <Piece r={by.stt} />,
    },
    {
      key: 'router',
      title: 'Router',
      target: 'routing',
      body: specialists === 0 ? (
        <>
          <span className="pipe__provider pipe__muted">Not needed</span>
          <span className="pipe__detail">No specialists below: this agent keeps the call</span>
        </>
      ) : (
        <>
          <span className="pipe__levels" aria-label="Router levels">
            <span className="pipe__level pipe__level--gate" title="Gate: rules on what is known about the caller">
              Gate
            </span>
            <span className="pipe__level pipe__level--pattern" title="Pattern: keywords">
              Pattern
            </span>
            <span className="pipe__level pipe__level--llm" title="LLM: only when the first two can't decide">
              LLM
            </span>
          </span>
          <span className="pipe__provider">{by.router.provider}</span>
          <span className="pipe__code">{by.router.model}</span>
          <span className="pipe__detail">
            {specialists} specialist{specialists === 1 ? '' : 's'} below{hasGate ? ', some behind a gate' : ''}
          </span>
        </>
      ),
    },
    {
      key: 'llm',
      title: 'Language model',
      target: 'models',
      source: by.llm.source,
      body: <Piece r={by.llm} />,
    },
    {
      key: 'tools',
      title: 'Tools',
      target: 'tools',
      body: (
        <>
          <span className="pipe__provider">{toolCount === 0 ? 'None' : `${toolCount} tool${toolCount === 1 ? '' : 's'}`}</span>
          <span className="pipe__detail">Run before the reply, when they apply</span>
        </>
      ),
    },
    {
      key: 'tts',
      title: 'Text to speech',
      target: 'models',
      source: by.tts.source,
      body: <Piece r={by.tts} />,
    },
  ]

  return (
    <ol className="pipe" aria-label="How this agent is built">
      {blocks.map((b) => (
        <li key={b.key} className={`pipe__step pipe__step--${b.key}`}>
          <button type="button" className="pipe__block" onClick={() => onOpen(b.target)}>
            <span className="pipe__title">
              {b.title}
              {b.source && (
                <span className={`pipe__source pipe__source--${b.source}`} title="Where this choice comes from">
                  {SOURCE[b.source]}
                </span>
              )}
            </span>
            {b.body}
          </button>
        </li>
      ))}
    </ol>
  )
}

function Piece({ r }: { r: Resolved }) {
  return (
    <>
      <span className="pipe__provider">{r.provider}</span>
      <span className="pipe__code">{r.model}</span>
      {r.detail && <span className="pipe__detail">{r.detail}</span>}
      {!r.available && <span className="pipe__warn">Can’t run on this server: no API key</span>}
    </>
  )
}
