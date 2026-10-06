import type { Project } from '../types'
import type { ProjectTab, Route } from '../route'
import { routeHash } from '../route'
import { Icon, type IconName } from './Icon'
import { Orb } from './Orb'
import { useOwner } from '../auth'

interface Props {
  route: Route
  projects: Project[]
  onSearch: () => void
  foot: React.ReactNode
}

const MAX_AGENTS = 5

/** Two levels, like the platforms this borrows from: the workspace (every
 * agent, shared knowledge and tools, all calls), and inside one agent its
 * own sections. The level changes with the route. */
export function Sidebar({ route, projects, onSearch, foot }: Props) {
  const owner = useOwner()
  const project = route.view === 'project' ? projects.find((p) => p.id === route.pid) : undefined

  return (
    <nav className="side" aria-label="Main">
      <a className="side__brand" href="#/">
        <BrandMark />
        Voice Orchestrator
      </a>
      <button type="button" className="side__search" onClick={onSearch}>
        <Icon name="search" />
        <span>Search and jump</span>
        <kbd>⌘K</kbd>
      </button>

      {route.view === 'project' ? (
        <ProjectNav route={route} project={project} />
      ) : (
        <>
          <Link href="#/" icon="home" label="Overview" active={route.view === 'overview'} />
          <Link href="#/call" icon="phone" label="Start a call" active={route.view === 'call'} />

          <Group
            title="Agents"
            action={
              owner ? (
                <a className="side__add" href="#/new-agent" aria-label="New agent" title="New agent">
                  <Icon name="plus" />
                </a>
              ) : null
            }
          >
            {projects.slice(0, MAX_AGENTS).map((p) => (
              <a key={p.id} className="side__link side__link--agent" href={`#/agents/${encodeURIComponent(p.id)}/agent`}>
                <Orb seed={p.id} size={18} />
                <span className="side__label">{p.name}</span>
              </a>
            ))}
            <Link
              href="#/agents"
              icon="agents"
              label={projects.length > MAX_AGENTS ? `All agents (${projects.length})` : 'All agents'}
              active={route.view === 'agents'}
            />
          </Group>

          <Group title="Configure">
            <Link href="#/knowledge" icon="book" label="Knowledge" active={route.view === 'knowledge'} />
            <Link href="#/tools" icon="plug" label="Tools" active={route.view === 'tools'} />
          </Group>

          <Group title="Monitor">
            <Link href="#/calls" icon="list" label="Calls" active={route.view === 'calls'} />
            <Link href="#/analytics" icon="chart" label="Analytics" active={route.view === 'analytics'} />
          </Group>
        </>
      )}

      <div className="side__foot">{foot}</div>
    </nav>
  )
}

function ProjectNav({ route, project }: { route: Extract<Route, { view: 'project' }>; project?: Project }) {
  const go = (tab: ProjectTab) => routeHash({ view: 'project', pid: route.pid, tab })
  const items: { tab: ProjectTab; label: string; icon: IconName; hide?: boolean }[][] = [
    [{ tab: 'overview', label: 'Overview', icon: 'chart' }],
    [
      { tab: 'agent', label: project?.kind === 'workflow' ? 'Agents' : 'Agent', icon: 'user' },
      { tab: 'workflow', label: 'Workflow', icon: 'flow', hide: project?.kind !== 'workflow' },
      { tab: 'models', label: 'Models', icon: 'sliders' },
    ],
    [
      { tab: 'calls', label: 'Calls', icon: 'list' },
      { tab: 'developer', label: 'Developer', icon: 'code' },
    ],
  ]
  const titles = ['', 'Configure', 'Monitor']
  return (
    <>
      <div className="side__scope">
        <a className="side__back" href="#/agents">
          <Icon name="back" />
          Back to workspace
        </a>
        <div className="side__current">
          <Orb seed={route.pid} size={22} />
          <span>
            <strong>{project?.name ?? route.pid}</strong>
            <small>{project ? (project.kind === 'single' ? 'Single agent' : `Workflow, ${project.agent_count} agents`) : ''}</small>
          </span>
        </div>
      </div>
      {items.map((group, i) => (
        <Group key={i} title={titles[i]}>
          {group
            .filter((it) => !it.hide)
            .map((it) => (
              <Link key={it.tab} href={go(it.tab)} icon={it.icon} label={it.label} active={route.tab === it.tab} />
            ))}
        </Group>
      ))}
      <Group title="Try it">
        <Link href={`#/call/${encodeURIComponent(route.pid)}`} icon="phone" label="Call this agent" active={false} />
      </Group>
    </>
  )
}

function Group({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="side__group">
      {title && (
        <div className="side__title">
          {title}
          {action}
        </div>
      )}
      {children}
    </div>
  )
}

function Link({ href, icon, label, active }: { href: string; icon: IconName; label: string; active: boolean }) {
  return (
    <a className="side__link" href={href} aria-current={active ? 'page' : undefined}>
      <Icon name={icon} />
      <span className="side__label">{label}</span>
    </a>
  )
}

export function BrandMark() {
  // One line in, three routes out — colored by router level.
  return (
    <svg className="side__mark" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
      <path d="M3 12h6" stroke="var(--ink)" />
      <path d="M9 12c3 0 4-6 8-6h4" stroke="var(--gate)" />
      <path d="M9 12h12" stroke="var(--pattern)" />
      <path d="M9 12c3 0 4 6 8 6h4" stroke="var(--llm)" />
      <circle cx="9" cy="12" r="2" fill="var(--ink)" stroke="none" />
    </svg>
  )
}
