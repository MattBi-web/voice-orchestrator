import { useEffect, useState } from 'react'
import type { KnowledgeDoc } from '../types'
import { api } from '../api'

interface Props {
  values: string[]
  onChange: (values: string[]) => void
}

/** Blocco 5: the agent's knowledge files as checkboxes over the documents
 * that actually exist (Knowledge base tab), instead of free-text file names
 * — a typo there used to fail silently (the agent just never found
 * anything). A name the agent already has but with no file behind it stays
 * listed, flagged, so it can be removed rather than silently dropped. */
export function KnowledgePicker({ values, onChange }: Props) {
  const [docs, setDocs] = useState<KnowledgeDoc[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api
      .listKnowledge()
      .then((r) => setDocs(r.documents.filter((d) => d.exists)))
      .catch(() => setFailed(true))
  }, [])

  const toggle = (name: string) =>
    onChange(values.includes(name) ? values.filter((v) => v !== name) : [...values, name])

  const known = new Set((docs ?? []).map((d) => d.name))
  const missing = values.filter((v) => docs && !known.has(v))

  return (
    <div className="field">
      <label>Knowledge</label>
      {failed ? (
        <p className="error">Couldn't load the documents.</p>
      ) : docs === null ? (
        <p className="kb-muted">Loading…</p>
      ) : docs.length === 0 && missing.length === 0 ? (
        <p className="kb-muted">No documents yet. Add one under Knowledge.</p>
      ) : (
        <div className="kb-picker">
          {docs.map((d) => (
            <label key={d.name} className="kb-check">
              <input type="checkbox" checked={values.includes(d.name)} onChange={() => toggle(d.name)} />
              <code>{d.name}</code>
              <span className="kb-muted">{d.chunk_count} passages</span>
            </label>
          ))}
          {missing.map((name) => (
            <label key={name} className="kb-check">
              <input type="checkbox" checked onChange={() => toggle(name)} />
              <code>{name}</code>
              <span className="kb-missing">file missing</span>
            </label>
          ))}
        </div>
      )}
      <p className="mcp-panel__hint">
        The agent also needs the <code>knowledge_lookup</code> tool to search these.
      </p>
    </div>
  )
}
