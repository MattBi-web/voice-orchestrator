/** A small, reusable "string -> string map" editor — one key/value pair of
 * text inputs per row, an add button, a remove button per row. Used for
 * webhook tool headers (ListEditor.tsx's single-string sibling). Duplicate
 * keys while typing are allowed transiently (the last one wins on submit),
 * same trade-off every other editor here makes for simplicity. */
interface Props {
  label: string
  values: Record<string, string>
  keyPlaceholder?: string
  valuePlaceholder?: string
  hint?: string
  onChange: (values: Record<string, string>) => void
}

export function KeyValueEditor({ label, values, keyPlaceholder, valuePlaceholder, hint, onChange }: Props) {
  const entries = Object.entries(values)

  const update = (i: number, key: string, value: string) => {
    const next = [...entries]
    next[i] = [key, value]
    onChange(Object.fromEntries(next))
  }
  const remove = (i: number) => onChange(Object.fromEntries(entries.filter((_, idx) => idx !== i)))
  const add = () => onChange(Object.fromEntries([...entries, ['', '']]))

  return (
    <div className="field">
      <label>{label}</label>
      {hint && <p className="field-hint">{hint}</p>}
      {entries.map(([k, v], i) => (
        <div className="list-row" key={i}>
          <input value={k} placeholder={keyPlaceholder} onChange={(e) => update(i, e.target.value, v)} />
          <input value={v} placeholder={valuePlaceholder} onChange={(e) => update(i, k, e.target.value)} />
          <button type="button" className="btn-icon" onClick={() => remove(i)} aria-label={`Remove ${label} item`}>
            ×
          </button>
        </div>
      ))}
      <button type="button" className="btn-link" onClick={add}>
        + Add
      </button>
    </div>
  )
}
