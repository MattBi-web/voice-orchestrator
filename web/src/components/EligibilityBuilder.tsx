import { useState } from 'react'

interface Props {
  value: string
  onChange: (value: string) => void
}

const KNOWN_FIELDS = ['authenticated', 'channel', 'transferred', 'call_ended', 'region']

type Simple = { field: string; op: '==' | '!='; value: string } | null

/** routing/gate.py's eligibility expressions are a full boolean mini-language
 * ("authenticated == true and region != 'embargoed'") — a dropdown can't
 * represent all of that, so this only replaces free text for the common
 * single-comparison case (blocco 2's "real pickers" item). Anything with
 * "and"/"or"/"not" in it, or that doesn't parse as `field == value`, falls
 * back to the raw textarea it's always been — that's a deliberate scope
 * cut, not a bug: see docs/ROADMAP.md. */
function parseSimple(expr: string): Simple {
  const trimmed = expr.trim()
  if (!trimmed) return null
  if (/\b(and|or|not)\b/i.test(trimmed)) return null
  const m = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=)\s*(.+)$/)
  if (!m) return null
  let value = m[3].trim()
  if (value.startsWith("'") && value.endsWith("'") && value.length >= 2) {
    value = value.slice(1, -1)
  } else if (!/^(true|false)$/i.test(value)) {
    return null // not a quoted string and not a bare boolean -> don't guess
  }
  return { field: m[1], op: m[2] as '==' | '!=', value }
}

function render(simple: Simple): string {
  if (!simple || !simple.field) return ''
  const isBool = /^(true|false)$/i.test(simple.value)
  const value = isBool ? simple.value.toLowerCase() : `'${simple.value}'`
  return `${simple.field} ${simple.op} ${value}`
}

export function EligibilityBuilder({ value, onChange }: Props) {
  const parsed = parseSimple(value)
  const [advanced, setAdvanced] = useState(() => value.trim() !== '' && parsed === null)

  if (advanced) {
    return (
      <div className="field">
        <label>Who can reach this agent</label>
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="e.g. authenticated == true and region != 'embargoed'" />
        <button type="button" className="btn-link" onClick={() => setAdvanced(false)}>
          Use the simple builder
        </button>
      </div>
    )
  }

  const current: Simple = parsed ?? { field: '', op: '==', value: 'true' }

  return (
    <div className="field">
      <label>Who can reach this agent</label>
      <div className="eligibility-builder">
        <input
          list="eligibility-fields"
          placeholder="field, e.g. authenticated"
          value={current.field}
          onChange={(e) => onChange(render({ ...current, field: e.target.value }))}
        />
        <datalist id="eligibility-fields">
          {KNOWN_FIELDS.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
        <select value={current.op} onChange={(e) => onChange(render({ ...current, op: e.target.value as '==' | '!=' }))}>
          <option value="==">equals</option>
          <option value="!=">is not</option>
        </select>
        <input
          placeholder="value, e.g. true or voice"
          value={current.value}
          onChange={(e) => onChange(render({ ...current, value: e.target.value }))}
        />
      </div>
      <p className="field-hint">
        The router's first level: a rule checked before anything else. Leave it empty to let every caller
        through. Combine conditions with and/or/not in the advanced editor.
      </p>
      <button type="button" className="btn-link" onClick={() => setAdvanced(true)}>
        Advanced editor
      </button>
    </div>
  )
}
