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

const SOURCE_LABEL: Record<string, string> = { text: 'testo', file: 'file', url: 'URL', '': 'file locale' }

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
      setError('Solo file .md o .txt: PDF e Word non sono ancora supportati.')
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
        <h3>Nuovo documento</h3>
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
              {m === 'text' ? 'Testo' : m === 'file' ? 'File' : 'URL'}
            </button>
          ))}
        </div>
      </div>

      {mode === 'url' ? (
        <>
          <div className="field">
            <label>Indirizzo della pagina</label>
            <input type="url" required placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <p className="mcp-panel__hint">
            Il server scarica la pagina e ne estrae il testo (titoli → sezioni). Serve internet in uscita dal server;
            indirizzi locali o di rete privata sono rifiutati.
          </p>
        </>
      ) : mode === 'file' ? (
        <div className="field">
          <label>File (.md o .txt)</label>
          <input type="file" accept=".md,.txt,text/markdown,text/plain" onChange={(e) => onFile(e.target.files?.[0])} />
        </div>
      ) : null}

      <div className="field">
        <label>Nome {mode === 'url' && '(facoltativo: altrimenti dal titolo della pagina)'}</label>
        <input
          required={mode !== 'url'}
          placeholder="es. orari_negozi.md"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {mode !== 'url' && (
        <div className="field">
          <label>Contenuto {mode === 'file' && content && `(${content.length} caratteri letti dal file)`}</label>
          <textarea
            required
            rows={mode === 'file' ? 8 : 12}
            placeholder={'## Sezione\nTesto della sezione…\n\n## Altra sezione\n…'}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <p className="mcp-panel__hint">
            Ogni sezione <code>##</code> diventa un chunk; una sezione lunga viene divisa per paragrafi.
          </p>
        </div>
      )}

      <label className="kb-check">
        <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
        Sovrascrivi se esiste già un documento con lo stesso nome
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>
        {busy ? (mode === 'url' ? 'Scarico…' : 'Salvo…') : 'Aggiungi'}
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
    if (!confirm(`Eliminare ${name}? Il file in data/knowledge/ viene cancellato.`)) return
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
            Elimina
          </button>
        )}
      </div>
      <dl className="kb-meta">
        <dt>Origine</dt>
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
        <dt>Dimensione</dt>
        <dd>
          {fmtSize(doc.size_bytes)} · {doc.chunk_count} chunk
        </dd>
        <dt>Usato da</dt>
        <dd>
          {doc.used_by.length ? (
            doc.used_by.map((a) => <code key={a}>{a}</code>).reduce<React.ReactNode[]>(
              (acc, el, i) => (i ? [...acc, ', ', el] : [el]),
              [],
            )
          ) : (
            <span className="kb-muted">nessun agente — aggiungilo dal form dell'agente</span>
          )}
        </dd>
      </dl>
      {doc.used_by.length > 0 && (
        <p className="mcp-panel__hint">Per eliminarlo, toglilo prima dagli agenti che lo usano.</p>
      )}

      <div className="kb-section__head">
        <h4>{showRaw ? 'Testo completo' : `Chunk (${doc.chunks.length})`}</h4>
        <button type="button" className="btn-link" onClick={() => setShowRaw(!showRaw)}>
          {showRaw ? 'mostra i chunk' : 'mostra il testo completo'}
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
      <h3>Prova una domanda</h3>
      <p className="mcp-panel__hint">
        Mostra i chunk che una domanda recupera, con il punteggio BM25: è la stessa ricerca che il tool{' '}
        <code>knowledge_lookup</code> fa durante una chiamata (che usa i primi 2). La ricerca è lessicale: una domanda
        in italiano trova poco in un documento in inglese.
      </p>
      <div className="kb-preview__row">
        <input
          required
          placeholder="es. la luce del router è rossa"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Dove cercare">
          <option value="">Tutti i documenti</option>
          {currentDoc && <option value={`doc:${currentDoc}`}>Solo {currentDoc}</option>}
          {agentsWithKb.length > 0 && (
            <optgroup label="Come lo vede un agente">
              {agentsWithKb.map((a) => (
                <option key={a.id} value={`agent:${a.id}`}>
                  {a.name || a.id}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <select value={topK} onChange={(e) => setTopK(Number(e.target.value))} aria-label="Quanti risultati">
          {[1, 2, 3, 5, 10].map((k) => (
            <option key={k} value={k}>
              top {k}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy}>
          {busy ? 'Cerco…' : 'Cerca'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="kb-results">
          {result.hits.length === 0 ? (
            <p className="kb-muted">
              Nessun chunk ha parole in comune con la domanda
              {result.documents.length ? ` (cercato in: ${result.documents.join(', ')})` : ' (nessun documento)'}. In
              chiamata, l'agente non riceverebbe nessun passaggio.
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
                    {scope.startsWith('agent:') && i < 2 && <span className="kb-tag">usato dall'agente</span>}
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
        <h2>Knowledge base</h2>
        {owner && (
          <button type="button" onClick={() => setPane({ kind: 'add' })}>
            + Nuovo documento
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className="convos__layout">
          <ul className="convos__list">
            {docs.length === 0 && <li className="kb-muted kb-empty">Nessun documento.</li>}
            {docs.map((d) => (
              <li key={d.name}>
                <button
                  type="button"
                  className={currentDoc === d.name ? 'convos__item convos__item--active' : 'convos__item'}
                  onClick={() => (d.exists ? open(d.name) : undefined)}
                  disabled={!d.exists}
                  title={d.exists ? undefined : 'Nessun file con questo nome in data/knowledge/'}
                >
                  <span className="convos__item-agent">{d.name}</span>
                  <span className="convos__item-time">
                    {d.exists ? (
                      <>
                        {d.chunk_count} chunk · {fmtSize(d.size_bytes)} · {SOURCE_LABEL[d.source_type]}
                      </>
                    ) : (
                      <span className="kb-missing">file mancante — usato da {d.used_by.join(', ')}</span>
                    )}
                  </span>
                  {d.exists && (
                    <span className="convos__item-time">
                      {d.used_by.length ? `usato da ${d.used_by.join(', ')}` : 'non usato da nessun agente'}
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
              <p className="kb-muted">Scegli un documento a sinistra per vederne i chunk, o aggiungine uno nuovo.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
