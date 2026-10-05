/** The router's three levels, always with the same name and color
 * (tokens in index.css): gate → slate, pattern → teal, LLM → amber. */
export const LEVELS: Record<string, { label: string; className: string; what: string }> = {
  gate_only: { label: 'Gate', className: 'level level--gate', what: 'Only one agent was allowed, so no choice was needed.' },
  pattern: { label: 'Pattern', className: 'level level--pattern', what: 'A keyword picked the agent, no model call.' },
  llm_fallback: { label: 'LLM', className: 'level level--llm', what: 'Keywords were ambiguous, so a model chose.' },
}

export function LevelChip({ level }: { level: string }) {
  const l = LEVELS[level]
  if (!l) return <span className="level level--gate">{level}</span>
  return (
    <span className={l.className} title={l.what}>
      {l.label}
    </span>
  )
}

/** Where a recorded call came from, in words a visitor understands. */
export const SOURCE_LABELS: Record<string, string> = {
  voice: 'Voice call',
  route_test: 'Text test',
  chat: 'CLI chat',
}

/** Same hues as the CSS tokens, for SVG charts. */
export const LEVEL_HEX: Record<string, string> = {
  gate_only: '#56657a',
  pattern: '#0f8a8a',
  llm_fallback: '#b7791f',
}

export const formatWhen = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
