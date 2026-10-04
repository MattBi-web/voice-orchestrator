import { useEffect, useState } from 'react'
import type { AnalysisConfig, DataItemType } from '../types'
import { api, ApiError } from '../api'

const TYPES: DataItemType[] = ['string', 'boolean', 'integer', 'number']

/** Family-wide success criteria + data-collection fields, edited and saved
 * as one unit (PUT /api/analysis/config). Saving doesn't touch analyses
 * already run — re-analyzing a call is an explicit action. */
export function AnalysisConfigEditor() {
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
      <p className="mcp-panel__hint">
        Valgono per tutta la famiglia di agenti, non per un singolo agente: una chiamata passa da più agenti ed è la
        chiamata intera che si valuta. Modificarli non cambia le analisi già fatte: usa "Rianalizza" su una chiamata
        per rivalutarla.
      </p>
      {error && <p className="error">{error}</p>}

      <h3>Criteri di successo</h3>
      {cfg.criteria.map((c, i) => (
        <div className="analysis-config__row" key={i}>
          <div className="analysis-config__cols">
            <input
              required
              placeholder="id, es. richiesta_risolta"
              value={c.id}
              onChange={(e) =>
                patch({ ...cfg, criteria: cfg.criteria.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)) })
              }
            />
            <input
              placeholder="nome visibile"
              value={c.name}
              onChange={(e) =>
                patch({ ...cfg, criteria: cfg.criteria.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })
              }
            />
            <button
              type="button"
              className="btn-icon"
              aria-label={`Rimuovi criterio ${c.id}`}
              onClick={() => patch({ ...cfg, criteria: cfg.criteria.filter((_, j) => j !== i) })}
            >
              ×
            </button>
          </div>
          <textarea
            required
            rows={2}
            placeholder="Cosa significa successo, in linguaggio naturale"
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
        onClick={() => patch({ ...cfg, criteria: [...cfg.criteria, { id: '', name: '', prompt: '' }] })}
      >
        + aggiungi criterio
      </button>

      <h3>Dati da estrarre</h3>
      {cfg.data_items.map((d, i) => (
        <div className="analysis-config__row" key={i}>
          <div className="analysis-config__cols">
            <input
              required
              placeholder="id, es. motivo_chiamata"
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
              aria-label={`Rimuovi campo ${d.id}`}
              onClick={() => patch({ ...cfg, data_items: cfg.data_items.filter((_, j) => j !== i) })}
            >
              ×
            </button>
          </div>
          <textarea
            required
            rows={2}
            placeholder="Cosa estrarre dalla chiamata"
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
        + aggiungi campo
      </button>

      <div className="form-actions">
        <button type="submit" disabled={saving}>
          {saving ? 'Salvataggio…' : 'Salva'}
        </button>
        {saved && <span className="analysis-config__saved">Salvato.</span>}
      </div>
    </form>
  )
}
