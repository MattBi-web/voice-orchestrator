/** Hash routes (blocco 8), so a project, a tab or an agent has a link that
 * can be shared or reloaded:
 *   #/                         overview
 *   #/agents                   all agents (projects)
 *   #/agents/<pid>             a project, Build tab
 *   #/agents/<pid>/<tab>[/<agent>]
 *   #/call[/<pid>]             start a call
 *   #/knowledge  #/tools  #/calls  #/analytics */

export type ProjectTab = 'build' | 'models' | 'calls' | 'developer'

export type Route =
  | { view: 'overview' }
  | { view: 'agents' }
  | { view: 'project'; pid: string; tab: ProjectTab; agent?: string }
  | { view: 'call'; pid?: string }
  | { view: 'calls'; call?: string }
  | { view: 'knowledge' | 'tools' | 'analytics' }

const TABS: ProjectTab[] = ['build', 'models', 'calls', 'developer']

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const [head, a, b, c] = parts
  switch (head) {
    case undefined:
      return { view: 'overview' }
    case 'agents':
      if (!a) return { view: 'agents' }
      return { view: 'project', pid: a, tab: TABS.includes(b as ProjectTab) ? (b as ProjectTab) : 'build', agent: c }
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
      return '#/agents'
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
