import type { Verdict } from '../types'

// Status colours are reserved for state and always ship with an icon and a
// text label — colour is never the only signal (same rule the dashboard's
// charts follow). The label stays in the normal text colour; only the icon
// carries the status hue.
const META: Record<Verdict, { icon: string; label: string; className: string }> = {
  success: { icon: '✓', label: 'Passed', className: 'verdict--success' },
  failure: { icon: '✕', label: 'Failed', className: 'verdict--failure' },
  unknown: { icon: '?', label: 'Unclear', className: 'verdict--unknown' },
}

export function VerdictChip({ verdict }: { verdict: Verdict | null | undefined }) {
  if (!verdict) {
    return <span className="verdict verdict--none">Not evaluated</span>
  }
  const m = META[verdict]
  return (
    <span className={`verdict ${m.className}`}>
      <span className="verdict__icon" aria-hidden="true">
        {m.icon}
      </span>
      {m.label}
    </span>
  )
}
