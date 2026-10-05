import { useEffect, useMemo, useState } from 'react'
import type { Agent, KnowledgeDoc, KnowledgeDocDetail, KnowledgeHit } from '../types'
import { api, ApiError } from '../api'
import { flatten } from '../tree'
import { useOwner } from '../auth'

/** Blocco 5 — the knowledge base tab. Documents are the files in
 * data/knowledge/ (the same ones the CLI and the voice worker read); this tab
 * lists them, adds new ones (pasted text, a .md/.txt file, a web page), shows
 * how each is cut into chunks, and previews which chunks a question retrieves
 * — through the same search the knowledge_lookup tool runs mid-call. */

type AddMode = 'text' | 'file' | 'url'
type Pane = { kind: 'doc'; name: string } | { kind: 'add' } | { kind: 'none' }

const SOURCE_LABEL: Record<string, string> = { text: 'Pasted text', file: 'Uploaded file', url: 'Web page', '': 'Bundled with the demo' }

function fmtSize(bytes: number) {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}

function errText(err: unknown) {
  return err instanceof ApiError ? err.message : String(err)
}

function AddDocument({ onAdded }: { onAdded: (name: string) => void }) {
  const [mode, setMode] = useState<AddMode>('text')
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [url, setUrl] = useState('')
  const [overwrite, setOverwrite] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onFile = async (file: File | undefined) => {
    if (!file) return
    setError(null)
    if (!/\.(md|txt)$/i.test(file.name)) {
      setError('Only .md and .txt files can be added. PDF and Word are not supported yet.')
      return
    }
    setContent(await file.text())
    if (!name) setName(file.name)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const doc =
        mode === 'url'
          ? await api.addKnowledgeFromUrl({ url, name: name || undefined, overwrite })
          : await api.addKnowledge({ name, content, source_type: mode, overwrite })
      onAdded(doc.name)
    } catch (err) {
      setError(errText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="kb-section" onSubmit={submit}>
      <div className="kb-section__head">
        <h3>Add a document</h3>
        <div className="kb-modes" role="tablist">
          {(['text', 'file', 'url'] as AddMode[]).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              className={mode === m ? 'app__tab app__tab--active' : 'app__tab'}
              onClick={() => {
                setMode(m)
                setError(null)
              }}
            >
              {m === 'text' ? 'Paste text' : m === 'file' ? 'Upload file' : 'Web page'}
            </button>
          ))}
        </div>
      </div>

      {mode === 'url' ? (
        <>
          <div className="field">
            <label>Page address</label>
            <input type="url" required placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <p className="mcp-panel__hint">
            The page is downloaded and its headings become sections. Local and private network addresses are refused.
          </p>
        </>
      ) : mode === 'file' ? (
        <div className="field">
          <label>File (.md o .txt)</label>
          <input type="file" accept=".md,.txt,text/markdown,text/plain" onChange={(e) => onFile(e.target.files?.[0])} />
        </div>
      ) : null}

      <div className="field">
        <label>Name {mode === 'url' && '(optional: taken from the page title)'}</label>
        <input
          required={mode !== 'url'}
          placeholder="es. orari_negozi.md"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {mode !== 'url' && (
        <div className="field">
          <label>Content {mode === 'file' && content && `(${content.length} characters read from the file)`}</label>
          <textarea
            required
            rows={mode === 'file' ? 8 : 12}
            placeholder={'## Opening hours\nWe are open…\n\n## Returns\n…'}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <p className="mcp-panel__hint">
            Each <code>##</code> section becomes one passage the agent can retrieve; long sections are split by paragraph.
          </p>
        </div>
      )}

      <label className="kb-check">
        <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
        Replace a document with the same name
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>
        {busy ? (mode === 'url' ? 'Downloading…' : 'Adding…') : 'Add document'}
      </button>
    </form>
  )
}

function DocumentView({
  name,
  highlight,
  onDeleted,
}: {
  name: string
  highlight: number | null
  onDeleted: () => void
}) {
  const owner = useOwner()
  const [doc, setDoc] = useState<KnowledgeDocDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showRaw, setShowRaw] = useState(false)

  useEffect(() => {
    setDoc(null)
    setError(null)
    api
      .getKnowledge(name)
      .then(setDoc)
      .catch((err) => setError(errText(err)))
  }, [name])

  useEffect(() => {
    if (highlight === null || !doc) return
    document.getElementById(`kb-chunk-${highlight}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [highlight, doc])

  const remove = async () => {
    if (!confirm(`Delete ${name}? This can't be undone.`)) return
    try {
      await api.deleteKnowledge(name)
      onDeleted()
    } catch (err) {
      setError(errText(err))
    }
  }

  if (error) return <p className="error">{error}</p>
  if (!doc) return <p>Loading…</p>

  return (
    <section className="kb-section">
      <div className="kb-section__head">
        <h3>
          <code>{doc.name}</code>
        </h3>
        {owner && (
          <button type="button" className="btn-danger" onClick={remove} disabled={doc.used_by.length > 0}>
            Delete document
          </button>
        )}
      </div>
      <dl className="kb-meta">
        <dt>Source</dt>
        <dd>
          {SOURCE_LABEL[doc.source_type]}
          {doc.source_url && (
            <>
              {' — '}
              <a href={doc.source_url} target="_blank" rel="noreferrer">
                {doc.source_url}
              </a>
            </>
          )}
        </dd>
        <dt>Size</dt>
        <dd>
          {fmtSize(doc.size_bytes)}, {doc.chunk_count} passages
        </dd>
        <dt>Used by</dt>
        <dd>
          {doc.used_by.length ? (
            doc.used_by.map((a) => <code key={a}>{a}</code>).reduce<React.ReactNode[]>(
              (acc, el, i) => (i ? [...acc, ', ', el] : [el]),
              [],
            )
          ) : (
            <span className="kb-muted">no agent yet. Add it from an agent's Knowledge field.</span>
          )}
        </dd>
      </dl>
      {doc.used_by.length > 0 && (
        <p className="mcp-panel__hint">To delete it, first remove it from the agents that use it.</p>
      )}

      <div className="kb-section__head">
        <h4>{showRaw ? 'Full text' : `Passages (${doc.chunks.length})`}</h4>
        <button type="button" className="btn-link" onClick={() => setShowRaw(!showRaw)}>
          {showRaw ? 'Show passages' : 'Show full text'}
        </button>
      </div>
      {showRaw ? (
        <pre className="kb-raw">{doc.content}</pre>
      ) : (
        <ol className="kb-chunks">
          {doc.chunks.map((c) => (
            <li
              key={c.index}
              id={`kb-chunk-${c.index}`}
              className={c.index === highlight ? 'kb-chunk kb-chunk--hit' : 'kb-chunk'}
            >
              <span className="kb-chunk__idx">#{c.index}</span>
              <pre>{c.text}</pre>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function SearchPreview({
  root,
  docs,
  currentDoc,
  onOpenHit,
}: {
  root: Agent | null
  docs: KnowledgeDoc[]
  currentDoc: string | null
  onOpenHit: (hit: KnowledgeHit) => void
}) {
  const [query, setQuery] = useState('')
  // "" = all documents, "doc:<name>" = one document, "agent:<id>" = that agent's documents
  const [scope, setScope] = useState('')
  const [topK, setTopK] = useState(3)
  const [result, setResult] = useState<{ documents: string[]; hits: KnowledgeHit[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const agentsWithKb = useMemo(() => {
    const ids = new Set(docs.flatMap((d) => d.used_by))
    return flatten(root).filter((a) => ids.has(a.id))
  }, [root, docs])

  const run = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = scope.startsWith('agent:')
        ? { query, agent_id: scope.slice(6), top_k: topK }
        : { query, documents: scope.startsWith('doc:') ? [scope.slice(4)] : [], top_k: topK }
      setResult(await api.searchKnowledge(body))
    } catch (err) {
      setError(errText(err))
    } finally {
      setBusy(false)
    }
  }

  const max = result?.hits.reduce((m, h) => Math.max(m, h.score), 0) || 1

  return (
    <form className="kb-section kb-preview" onSubmit={run}>
      <h3>Test a question</h3>
      <p className="mcp-panel__hint">
        See which passages a question retrieves, and how strongly. It is the same search an agent runs during a
        call, which uses the top two. Matching is by words, so an Italian question finds little in an English
        document.
      </p>
      <div className="kb-preview__row">
        <input
          required
          placeholder="e.g. the router light is red"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Where to search">
          <option value="">All documents</option>
          {currentDoc && <option value={`doc:${currentDoc}`}>Only {currentDoc}</option>}
          {agentsWithKb.length > 0 && (
            <optgroup label="As an agent sees it">
              {agentsWithKb.map((a) => (
                <option key={a.id} value={`agent:${a.id}`}>
                  {a.name || a.id}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <select value={topK} onChange={(e) => setTopK(Number(e.target.value))} aria-label="How many results">
          {[1, 2, 3, 5, 10].map((k) => (
            <option key={k} value={k}>
              top {k}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy}>
          {busy ? 'Searching…' : 'Search'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="kb-results">
          {result.hits.length === 0 ? (
            <p className="kb-muted">
              No passage shares a word with the question
              {result.documents.length ? ` (searched ${result.documents.join(', ')})` : ' (no documents)'}. On a call,
              the agent would get nothing to answer from.
            </p>
          ) : (
            <ol className="kb-hits">
              {result.hits.map((h, i) => (
                <li key={`${h.document}-${h.index}`} className="kb-hit">
                  <div className="kb-hit__head">
                    <span className="kb-hit__rank">{i + 1}</span>
                    <button type="button" className="btn-link" onClick={() => onOpenHit(h)}>
                      {h.document} #{h.index}
                    </button>
                    {scope.startsWith('agent:') && i < 2 && <span className="kb-tag">used on a call</span>}
                    <span className="kb-hit__score">{h.score.toFixed(2)}</span>
                  </div>
                  <div className="kb-hit__bar" aria-hidden>
                    <span style={{ width: `${(h.score / max) * 100}%` }} />
                  </div>
                  <pre>{h.text}</pre>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </form>
  )
}

export function KnowledgeBase({ root }: { root: Agent | null }) {
  const owner = useOwner()
  const [docs, setDocs] = useState<KnowledgeDoc[]>([])
  const [pane, setPane] = useState<Pane>({ kind: 'none' })
  const [highlight, setHighlight] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const res = await api.listKnowledge()
      setDocs(res.documents)
      setError(null)
    } catch (err) {
      setError(errText(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const open = (name: string, chunk: number | null = null) => {
    setPane({ kind: 'doc', name })
    setHighlight(chunk)
  }

  const currentDoc = pane.kind === 'doc' ? pane.name : null

  return (
    <div className="kb">
      <div className="dashboard__toolbar">
        {owner && (
          <button type="button" onClick={() => setPane({ kind: 'add' })}>
            Add document
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className="convos__layout">
          <ul className="convos__list">
            {docs.length === 0 && <li className="kb-muted kb-empty">No documents yet.</li>}
            {docs.map((d) => (
              <li key={d.name}>
                <button
                  type="button"
                  className={currentDoc === d.name ? 'convos__item convos__item--active' : 'convos__item'}
                  onClick={() => (d.exists ? open(d.name) : undefined)}
                  disabled={!d.exists}
                  title={d.exists ? undefined : 'No document with this name exists'}
                >
                  <span className="convos__item-agent">{d.name}</span>
                  <span className="convos__item-time">
                    {d.exists ? (
                      <>
                        {d.chunk_count} passages · {fmtSize(d.size_bytes)}
                      </>
                    ) : (
                      <span className="kb-missing">Missing, but used by {d.used_by.join(', ')}</span>
                    )}
                  </span>
                  {d.exists && (
                    <span className="convos__item-time">
                      {d.used_by.length ? `Used by ${d.used_by.join(', ')}` : 'Not used by any agent'}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <div className="convos__detail">
            <SearchPreview root={root} docs={docs} currentDoc={currentDoc} onOpenHit={(h) => open(h.document, h.index)} />
            {pane.kind === 'add' ? (
              <AddDocument
                onAdded={async (name) => {
                  await load()
                  open(name)
                }}
              />
            ) : pane.kind === 'doc' ? (
              <DocumentView
                key={pane.name}
                name={pane.name}
                highlight={highlight}
                onDeleted={async () => {
                  setPane({ kind: 'none' })
                  await load()
                }}
              />
            ) : (
              <p className="kb-muted">Select a document to see the passages it is split into.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
