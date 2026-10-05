import { useEffect, useState } from 'react'
import type { Agent, AgentPipeline, Project } from '../types'
import { api, ApiError } from '../api'
import { flatten } from '../tree'
import { useOwner } from '../auth'

interface Props {
  project: Project
  root: Agent | null
  agentId: string
}

const PIECES: Record<string, string> = {
  stt: 'Speech to text',
  router: 'Router (LLM level)',
  llm: 'Language model',
  tts: 'Text to speech',
}

/** Blocco 8: the project as a developer sees it — the ids to call it by,
 * each agent's pipeline as the server resolves it, the configuration as
 * YAML (the same format as config/agents.yaml, so it can go into the repo
 * and the CLI), and the HTTP calls behind the test panel and the call page. */
export function DeveloperPanel({ project, root, agentId }: Props) {
  const owner = useOwner()
  const [pick, setPick] = useState(agentId)
  const [pipeline, setPipeline] = useState<AgentPipeline | null>(null)
  const [exported, setExported] = useState<{ yaml: string; json: unknown } | null>(null)
  const [format, setFormat] = useState<'yaml' | 'json'>('yaml')
  const [error, setError] = useState<string | null>(null)
  const [wrote, setWrote] = useState<string | null>(null)

  useEffect(() => {
    api.exportProject(project.id).then(setExported).catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [project.id, project.updated_at])

  useEffect(() => {
    if (!pick) return
    api
      .getPipeline(project.id, pick)
      .then(setPipeline)
      .catch(() => setPipeline(null))
  }, [project.id, pick, project.updated_at])

  const origin = window.location.origin
  const text = exported ? (format === 'yaml' ? exported.yaml : JSON.stringify(exported.json, null, 2)) : ''
  const curl = `# Start a text conversation on the real router (visitors always get placeholder replies)
curl -s -X POST ${origin}/api/test/conversations \\
  -H 'Content-Type: application/json' \\
  -d '{"project_id": "${project.id}"}'

# One caller turn: returns the same event a live call publishes
curl -s -X POST ${origin}/api/test/conversations/<id>/turns \\
  -H 'Content-Type: application/json' \\
  -d '{"utterance": "Buongiorno, ho una domanda"}'

# A LiveKit room token for a voice call to this agent
curl -s -X POST ${origin}/api/voice/token \\
  -H 'Content-Type: application/json' \\
  -d '{"project_id": "${project.id}"}'`

  const download = () => {
    const blob = new Blob([text], { type: format === 'yaml' ? 'text/yaml' : 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${project.id}.${format === 'yaml' ? 'yaml' : 'json'}`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const writeToRepo = async () => {
    if (!confirm('Overwrite config/agents.yaml with this project? The CLI reads that file; uncommitted changes in it will be lost.')) return
    try {
      const r = await api.exportAgents()
      setWrote(`Wrote ${r.agent_count} agents to ${r.path}.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <div className="dev">
      <section className="dev__block">
        <h2>Identifiers</h2>
        <dl className="dev__ids">
          <dt>Project id</dt>
          <dd>
            <code>{project.id}</code>
          </dd>
          <dt>Agents</dt>
          <dd className="dev__agents">
            {flatten(root).map((a) => (
              <code key={a.id} title={a.name}>
                {'  '.repeat(a.depth)}
                {a.id}
              </code>
            ))}
          </dd>
        </dl>
      </section>

      <section className="dev__block">
        <div className="dev__head">
          <h2>Resolved pipeline</h2>
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Agent">
            {flatten(root).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name || a.id}
              </option>
            ))}
          </select>
        </div>
        <p className="dev__lede">What the server will actually run for this agent, after inheritance and overrides.</p>
        {pipeline && (
          <table className="dev__table">
            <thead>
              <tr>
                <th scope="col">Piece</th>
                <th scope="col">Provider</th>
                <th scope="col">Model</th>
                <th scope="col">Settings</th>
                <th scope="col">From</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.steps.map((s) => (
                <tr key={s.component}>
                  <td>{PIECES[s.component]}</td>
                  <td>
                    <code>{s.provider === 'fake' ? 'none (placeholder)' : s.provider || '—'}</code>
                    {!s.available && <span className="dev__warn"> can’t run here</span>}
                  </td>
                  <td>
                    {s.provider === 'fake' ? '—' : <code>{s.model || 'default'}</code>}
                  </td>
                  <td>
                    {s.component === 'stt' && <code>language={s.language || 'default'}</code>}
                    {s.component === 'tts' && <code>voice={s.voice_id || 'default'}</code>}
                    {s.component === 'llm' && s.provider !== 'fake' && <code>temperature={s.temperature ?? 'default'}</code>}
                  </td>
                  <td>{s.source === 'agent' ? 'Agent override' : s.source === 'project' ? 'Project default' : 'Server default'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="dev__block">
        <div className="dev__head">
          <h2>Configuration</h2>
          <div className="seg" role="group" aria-label="Format">
            <button type="button" aria-pressed={format === 'yaml'} onClick={() => setFormat('yaml')}>
              YAML
            </button>
            <button type="button" aria-pressed={format === 'json'} onClick={() => setFormat('json')}>
              JSON
            </button>
          </div>
        </div>
        <p className="dev__lede">
          Same format as <code>config/agents.yaml</code>: run it with the CLI (
          <code>VOICE_ORCH_AGENTS_FILE={project.id}.yaml voice-orchestrator chat</code>) or keep it in the repo.
        </p>
        <pre className="dev__code">{text}</pre>
        <div className="dev__actions">
          <button type="button" className="btn-secondary" onClick={() => navigator.clipboard?.writeText(text)}>
            Copy
          </button>
          <button type="button" className="btn-secondary" onClick={download}>
            Download
          </button>
          {owner && project.id === 'demo' && (
            <button type="button" className="btn-secondary" onClick={writeToRepo}>
              Write to config/agents.yaml
            </button>
          )}
          {wrote && <span className="form-actions__ok">{wrote}</span>}
        </div>
      </section>

      <section className="dev__block">
        <h2>API</h2>
        <p className="dev__lede">The calls behind the test panel and the call page.</p>
        <pre className="dev__code">{curl}</pre>
      </section>
      {error && <p className="error">{error}</p>}
    </div>
  )
}
