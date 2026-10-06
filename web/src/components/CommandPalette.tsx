import { useEffect, useMemo, useRef, useState } from 'react'
import type { Project } from '../types'
import { Icon, type IconName } from './Icon'
import { Orb } from './Orb'

interface Item {
  id: string
  label: string
  hint: string
  href: string
  icon?: IconName
  orb?: string
}

/** ⌘K / Ctrl+K: jump to any page, agent or agent section by typing. */
export function CommandPalette({ open, onClose, projects }: { open: boolean; onClose: () => void; projects: Project[] }) {
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const ref = useRef<HTMLDialogElement | null>(null)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) {
      setQ('')
      setActive(0)
      d.showModal()
    } else if (!open && d.open) d.close()
  }, [open])

  const items = useMemo<Item[]>(() => {
    const pages: Item[] = [
      { id: 'p-overview', label: 'Overview', hint: 'Page', href: '#/', icon: 'home' },
      { id: 'p-agents', label: 'All agents', hint: 'Page', href: '#/agents', icon: 'agents' },
      { id: 'p-new', label: 'New agent', hint: 'Action', href: '#/new-agent', icon: 'plus' },
      { id: 'p-call', label: 'Start a call', hint: 'Action', href: '#/call', icon: 'phone' },
      { id: 'p-knowledge', label: 'Knowledge', hint: 'Page', href: '#/knowledge', icon: 'book' },
      { id: 'p-tools', label: 'Tools', hint: 'Page', href: '#/tools', icon: 'plug' },
      { id: 'p-calls', label: 'Calls', hint: 'Page', href: '#/calls', icon: 'list' },
      { id: 'p-analytics', label: 'Analytics', hint: 'Page', href: '#/analytics', icon: 'chart' },
    ]
    const agents = projects.flatMap<Item>((p) => {
      const base = `#/agents/${encodeURIComponent(p.id)}`
      return [
        { id: `a-${p.id}`, label: p.name, hint: p.kind === 'single' ? 'Single agent' : 'Workflow', href: `${base}/agent`, orb: p.id },
        { id: `m-${p.id}`, label: `${p.name}: models`, hint: 'Agent section', href: `${base}/models`, icon: 'sliders' },
        { id: `c-${p.id}`, label: `${p.name}: calls`, hint: 'Agent section', href: `${base}/calls`, icon: 'list' },
        { id: `d-${p.id}`, label: `${p.name}: developer`, hint: 'Agent section', href: `${base}/developer`, icon: 'code' },
      ]
    })
    const all = [...agents.filter((a) => a.orb), ...pages, ...agents.filter((a) => !a.orb)]
    const needle = q.trim().toLowerCase()
    return needle ? all.filter((i) => i.label.toLowerCase().includes(needle)) : all.slice(0, 12)
  }, [projects, q])

  const go = (item: Item | undefined) => {
    if (!item) return
    window.location.hash = item.href
    onClose()
  }

  return (
    <dialog ref={ref} className="palette" onClose={onClose} aria-label="Search and jump">
      <div className="palette__input">
        <Icon name="search" />
        <input
          autoFocus
          value={q}
          placeholder="Search agents, pages and actions"
          onChange={(e) => {
            setQ(e.target.value)
            setActive(0)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((a) => Math.min(a + 1, items.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((a) => Math.max(a - 1, 0))
            } else if (e.key === 'Enter') {
              e.preventDefault()
              go(items[active])
            }
          }}
        />
        <kbd>Esc</kbd>
      </div>
      <ul className="palette__list" role="listbox">
        {items.length === 0 && <li className="palette__empty">Nothing matches “{q}”.</li>}
        {items.map((it, i) => (
          <li key={it.id} role="option" aria-selected={i === active}>
            <button type="button" onMouseEnter={() => setActive(i)} onClick={() => go(it)}>
              {it.orb ? <Orb seed={it.orb} size={18} /> : <Icon name={it.icon ?? 'chevron'} />}
              <span className="palette__label">{it.label}</span>
              <span className="palette__hint">{it.hint}</span>
            </button>
          </li>
        ))}
      </ul>
    </dialog>
  )
}
