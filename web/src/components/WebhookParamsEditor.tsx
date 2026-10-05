import type { WebhookParam } from '../types'

interface Props {
  values: WebhookParam[]
  onChange: (values: WebhookParam[]) => void
}

/** Each row is one WebhookParam: a name (the JSON body/query-string key),
 * where its value comes from ("slot" = CallSession.slots[value] at call
 * time, "literal" = the value typed here, sent as-is every time), and a
 * type used only to coerce a slot's string value (webhook_tool.py's
 * _coerce()) — this project never has an LLM fill tool arguments (see
 * tools/base.py), so these are the only two sources a webhook's "JSON
 * schema" parameters can be filled from. */
export function WebhookParamsEditor({ values, onChange }: Props) {
  const update = (i: number, patch: Partial<WebhookParam>) => {
    const next = [...values]
    next[i] = { ...next[i], ...patch }
    onChange(next)
  }
  const remove = (i: number) => onChange(values.filter((_, idx) => idx !== i))
  const add = () => onChange([...values, { name: '', source: 'slot', value: '', type: 'string' }])

  return (
    <div className="field">
      <label>Parametri</label>
      <p className="field-hint">
        Ogni parametro diventa una chiave nel body JSON (o nella query string per GET). "Da slot" legge il valore da{' '}
        <code>session.slots[...]</code> al momento della chiamata (es. <code>account_number</code>); "Letterale" lo
        fissa qui una volta per tutte.
      </p>
      {values.map((p, i) => (
        <div className="list-row webhook-params-row" key={i}>
          <input
            placeholder="nome parametro"
            value={p.name}
            onChange={(e) => update(i, { name: e.target.value })}
          />
          <select value={p.source} onChange={(e) => update(i, { source: e.target.value as WebhookParam['source'] })}>
            <option value="slot">Da slot</option>
            <option value="literal">Letterale</option>
          </select>
          <input
            placeholder={p.source === 'slot' ? 'nome dello slot' : 'valore fisso'}
            value={p.value}
            onChange={(e) => update(i, { value: e.target.value })}
          />
          <select value={p.type} onChange={(e) => update(i, { type: e.target.value as WebhookParam['type'] })}>
            <option value="string">testo</option>
            <option value="number">numero</option>
            <option value="boolean">booleano</option>
          </select>
          <button type="button" className="btn-icon" onClick={() => remove(i)} aria-label="Remove param">
            ×
          </button>
        </div>
      ))}
      <button type="button" className="btn-link" onClick={add}>
        + add parametro
      </button>
    </div>
  )
}
