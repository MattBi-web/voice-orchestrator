import type { ToolBinding } from '../types'

interface Props {
  values: ToolBinding[]
  availableTools: string[]
  onChange: (values: ToolBinding[]) => void
}

/** Each row is one ToolBinding: a known tool id (dropdown, from GET
 * /api/tools — so you can't typo a tool that doesn't exist) plus an
 * optional condition (free text, the same gate expression language
 * routing/gate.py evaluates for agent eligibility — e.g. "channel ==
 * 'voice'"). Empty condition = always eligible, same convention as the
 * backend. */
export function ToolsEditor({ values, availableTools, onChange }: Props) {
  const update = (i: number, patch: Partial<ToolBinding>) => {
    const next = [...values]
    next[i] = { ...next[i], ...patch }
    onChange(next)
  }
  const remove = (i: number) => onChange(values.filter((_, idx) => idx !== i))
  const add = () => onChange([...values, { id: availableTools[0] ?? '', condition: '' }])

  return (
    <div className="field">
      <label>Tools</label>
      {values.map((t, i) => (
        <div className="list-row tools-row" key={i}>
          <select value={t.id} onChange={(e) => update(i, { id: e.target.value })}>
            {availableTools.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
          <input
            placeholder="Only when… (optional), e.g. channel == 'voice'"
            value={t.condition}
            onChange={(e) => update(i, { condition: e.target.value })}
          />
          <button type="button" className="btn-icon" onClick={() => remove(i)} aria-label="Remove tool">
            ×
          </button>
        </div>
      ))}
      <button type="button" className="btn-link" onClick={add} disabled={availableTools.length === 0}>
        + Add tool
      </button>
    </div>
  )
}
