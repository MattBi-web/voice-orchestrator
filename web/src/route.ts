/** Hash routes, so every page, agent and setting has a link that can be
 * shared or reloaded:
 *   #/                                 overview
 *   #/agents                           all agents (projects)
 *   #/new-agent                        all agents, with the create dialog open
 *   #/agents/<pid>[/<tab>[/<agent>]]   inside an agent (project)
 *   #/call[/<pid>]                     start a call
 *   #/calls[/<call id>]  #/knowledge  #/tools  #/analytics
 * Redesign (blocco 9, 2): a project's sections are pages of their own in
 * the agent-scoped sidebar. "build" (blocco 8 links) opens "agent". */

export type ProjectTab = 'overview' | 'agent' | 'workflow' | 'models' | 'calls' | 'developer'

export type Route =
  | { view: 'overview' }
  | { view: 'agents'; create?: boolean }
  | { view: 'project'; pid: string; tab: ProjectTab; agent?: string }
  | { view: 'call'; pid?: string }
  | { view: 'calls'; call?: string }
  | { view: 'knowledge' | 'tools' | 'analytics' }

const TABS: ProjectTab[] = ['overview', 'agent', 'workflow', 'models', 'calls', 'developer']

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const [head, a, b, c] = parts
  switch (head) {
    case undefined:
      return { view: 'overview' }
    case 'new-agent':
      return { view: 'agents', create: true }
    case 'agents': {
      if (!a) return { view: 'agents' }
      const tab = b === 'build' ? 'agent' : TABS.includes(b as ProjectTab) ? (b as ProjectTab) : 'agent'
      return { view: 'project', pid: a, tab, agent: c }
    }
    case 'call':
      return { view: 'call', pid: a }
    case 'calls':
      return { view: 'calls', call: a }
    case 'knowledge':
    case 'tools':
    case 'analytics':
      return { view: head }
    default:
      return { view: 'overview' }
  }
}

export function routeHash(r: Route): string {
  switch (r.view) {
    case 'overview':
      return '#/'
    case 'agents':
      return r.create ? '#/new-agent' : '#/agents'
    case 'project':
      return `#/agents/${encodeURIComponent(r.pid)}/${r.tab}${r.agent ? `/${encodeURIComponent(r.agent)}` : ''}`
    case 'call':
      return r.pid ? `#/call/${encodeURIComponent(r.pid)}` : '#/call'
    case 'calls':
      return r.call ? `#/calls/${encodeURIComponent(r.call)}` : '#/calls'
    default:
      return `#/${r.view}`
  }
}
