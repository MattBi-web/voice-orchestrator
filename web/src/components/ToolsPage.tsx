import { McpServersPanel } from './McpServersPanel'
import { WebhookToolsPanel } from './WebhookToolsPanel'

const BUILT_IN: { id: string; what: string }[] = [
  { id: 'transfer_to_human', what: 'Hands the call to a human queue, passing along what was said so far.' },
  { id: 'end_call', what: 'Says goodbye and hangs up once the caller has nothing else to ask.' },
  { id: 'knowledge_lookup', what: "Grounds the reply in the agent's knowledge documents." },
  { id: 'check_account_status', what: "Looks up the caller's balance and due date (demo billing API)." },
]

/** Every action an agent can take, in one place: built-ins, HTTP webhooks,
 * MCP servers. Which agent uses which tool is set on the agent itself. */
export function ToolsPage({ onChanged }: { onChanged: () => void }) {
  return (
    <div className="tools-page">
      <section className="tools-page__section">
        <h2>Built-in</h2>
        <p className="section-lede">Always available. Add them to an agent from its Tools field.</p>
        <ul className="builtin-list">
          {BUILT_IN.map((t) => (
            <li key={t.id}>
              <code>{t.id}</code>
              <span>{t.what}</span>
            </li>
          ))}
        </ul>
      </section>
      <WebhookToolsPanel onChanged={onChanged} />
      <McpServersPanel onChanged={onChanged} />
    </div>
  )
}
