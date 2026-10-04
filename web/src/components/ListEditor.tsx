/** A small, reusable "list of strings" editor — one text input per item,
 * an add button, a remove button per row. Used for triggers and knowledge
 * filenames, which are both just string[] with no extra structure. */
interface Props {
  label: string
  values: string[]
  placeholder?: string
  onChange: (values: string[]) => void
}

export function ListEditor({ label, values, placeholder, onChange }: Props) {
  const update = (i: number, value: string) => {
    const next = [...values]
    next[i] = value
    onChange(next)
  }
  const remove = (i: number) => onChange(values.filter((_, idx) => idx !== i))
  const add = () => onChange([...values, ''])

  return (
    <div className="field">
      <label>{label}</label>
      {values.map((v, i) => (
        <div className="list-row" key={i}>
          <input value={v} placeholder={placeholder} onChange={(e) => update(i, e.target.value)} />
          <button type="button" className="btn-icon" onClick={() => remove(i)} aria-label={`Remove ${label} item`}>
            ×
          </button>
        </div>
      ))}
      <button type="button" className="btn-link" onClick={add}>
        + add
      </button>
    </div>
  )
}
