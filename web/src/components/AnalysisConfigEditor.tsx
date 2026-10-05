import { useEffect, useState } from 'react'
import type { AnalysisConfig, Criterion, CriterionKind, DataItemType } from '../types'
import { api, ApiError } from '../api'
import { useOwner } from '../auth'

const TYPES: DataItemType[] = ['string', 'boolean', 'integer', 'number']

const KINDS: { value: CriterionKind; label: string; expectedHint: string }[] = [
  { value: 'llm', label: 'Judged by a model', expectedHint: '' },
  {
    value: 'final_agent',
    label: 'Ended with agent',
    expectedHint: 'Expected agent IDs, comma-separated (empty: any agent but the receptionist)',
  },
  { value: 'tool_used', label: 'Tool was used', expectedHint: 'Tool IDs, comma-separated (any one is enough)' },
  { value: 'tool_not_used', label: 'Tool was not used', expectedHint: 'Tool IDs, comma-separated (none may appear)' },
]

const splitIds = (raw: string) =>
  raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

/** Family-wide success criteria + data-collection fields, edited and saved
 * as one unit (PUT /api/analysis/config). Saving doesn't touch analyses
 * already run — re-analyzing a call is an explicit action. */
export function AnalysisConfigEditor() {
  const owner = useOwner()
  const [cfg, setCfg] = useState<AnalysisConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .getAnalysisConfig()
      .then(setCfg)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [])

  if (!cfg) return error ? <p className="error">{error}</p> : <p>Loading…</p>

  const patch = (next: AnalysisConfig) => {
    setCfg(next)
    setSaved(false)
  }

  const patchCriterion = (i: number, change: Partial<Criterion>) =>
    patch({ ...cfg, criteria: cfg.criteria.map((x, j) => (j === i ? { ...x, ...change } : x)) })

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      setCfg(await api.putAnalysisConfig(cfg))
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="analysis-config" onSubmit={save}>
      <fieldset className="ro-fieldset" disabled={!owner}>
      <p className="mcp-panel__hint">
        Criteria apply to the whole call, not to one agent, because a call moves between agents. Changing them
        doesn't touch past evaluations: open a call and evaluate it again.
      </p>
      <p className="mcp-panel__hint">
        "Judged by a model" needs a language model configured; without one it stays unclear. The other kinds check
        facts in the transcript, so they always give a verdict.
      </p>
      {error && <p className="error">{error}</p>}

      <h3>Success criteria</h3>
      {cfg.criteria.map((c, i) => (
        <div className="analysis-config__row" key={i}>
          <div className="analysis-config__cols">
            <input
              required
              placeholder="ID, e.g. request_resolved"
              value={c.id}
              onChange={(e) =>
                patch({ ...cfg, criteria: cfg.criteria.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)) })
              }
            />
            <input
              placeholder="Display name"
              value={c.name}
              onChange={(e) =>
                patch({ ...cfg, criteria: cfg.criteria.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })
              }
            />
            <select
              aria-label={`Kind of criterion ${c.id}`}
              value={c.kind}
              onChange={(e) => patchCriterion(i, { kind: e.target.value as CriterionKind })}
            >
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-icon"
              aria-label={`Remove criterion ${c.id}`}
              onClick={() => patch({ ...cfg, criteria: cfg.criteria.filter((_, j) => j !== i) })}
            >
              ×
            </button>
          </div>
          {c.kind !== 'llm' && (
            <input
              // Uncontrolled (committed on blur, so "a, b" can be typed
              // freely): the key remounts it whenever the saved list or the
              // row's position changes, so it never shows a stale value.
              key={`expected-${i}-${c.expected.join(',')}`}
              required={c.kind !== 'final_agent'}
              placeholder={KINDS.find((k) => k.value === c.kind)?.expectedHint}
              defaultValue={c.expected.join(', ')}
              onBlur={(e) => patchCriterion(i, { expected: splitIds(e.target.value) })}
            />
          )}
          <textarea
            required={c.kind === 'llm'}
            rows={2}
            placeholder={
              c.kind === 'llm'
                ? 'What success means, in plain language'
                : 'Description (optional: this is a fact check)'
            }
            value={c.prompt}
            onChange={(e) =>
              patch({ ...cfg, criteria: cfg.criteria.map((x, j) => (j === i ? { ...x, prompt: e.target.value } : x)) })
            }
          />
        </div>
      ))}
      <button
        type="button"
        className="btn-link"
        onClick={() => patch({ ...cfg, criteria: [...cfg.criteria, { id: '', name: '', prompt: '', kind: 'llm', expected: [] }] })}
      >
        + Add criterion
      </button>

      <h3>Data to extract</h3>
      {cfg.data_items.map((d, i) => (
        <div className="analysis-config__row" key={i}>
          <div className="analysis-config__cols">
            <input
              required
              placeholder="ID, e.g. call_reason"
              value={d.id}
              onChange={(e) =>
                patch({ ...cfg, data_items: cfg.data_items.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)) })
              }
            />
            <select
              value={d.type}
              onChange={(e) =>
                patch({
                  ...cfg,
                  data_items: cfg.data_items.map((x, j) => (j === i ? { ...x, type: e.target.value as DataItemType } : x)),
                })
              }
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-icon"
              aria-label={`Remove field ${d.id}`}
              onClick={() => patch({ ...cfg, data_items: cfg.data_items.filter((_, j) => j !== i) })}
            >
              ×
            </button>
          </div>
          <textarea
            required
            rows={2}
            placeholder="What to extract from the call"
            value={d.description}
            onChange={(e) =>
              patch({
                ...cfg,
                data_items: cfg.data_items.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)),
              })
            }
          />
        </div>
      ))}
      <button
        type="button"
        className="btn-link"
        onClick={() =>
          patch({ ...cfg, data_items: [...cfg.data_items, { id: '', type: 'string', description: '' }] })
        }
      >
        + Add field
      </button>

      </fieldset>
      <div className="form-actions">
        <button type="submit" disabled={saving || !owner}>
          {saving ? 'Saving…' : 'Save criteria'}
        </button>
        {saved && <span className="analysis-config__saved">Saved.</span>}
      </div>
    </form>
  )
}
