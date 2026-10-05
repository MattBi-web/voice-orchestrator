import { useEffect, useMemo, useRef, useState } from 'react'
import type { Agent } from '../types'
import { api, ApiError } from '../api'
import { useOwner } from '../auth'

interface Props {
  root: Agent | null
  selectedId: string | null
  onSelect: (id: string) => void
  onAddChild: (parentId: string) => void
  onChanged: () => void
}

interface Pos {
  x: number
  y: number
}

const COL = 300
const ROW = 96
const NODE_W = 224
const NODE_H = 82

/** Left-to-right tree layout: x by depth, y by averaging children — used
 * only for nodes that have never been dragged (layout_x/layout_y both
 * null). A dragged node keeps the position the user gave it, forever,
 * until dragged again. */
function autoLayout(root: Agent): Map<string, Pos> {
  const positions = new Map<string, Pos>()
  let leafCounter = 0

  function visit(node: Agent, depth: number): number {
    if (node.children.length === 0) {
      const y = leafCounter * ROW
      leafCounter += 1
      positions.set(node.id, { x: depth * COL, y })
      return y
    }
    const childYs = node.children.map((c) => visit(c, depth + 1))
    const y = childYs.reduce((a, b) => a + b, 0) / childYs.length
    positions.set(node.id, { x: depth * COL, y })
    return y
  }
  visit(root, 0)
  return positions
}

/** Word-wrap a name into at most two lines that fit the node. */
function wrap(label: string, max = 25): string[] {
  const words = label.split(/\s+/)
  const lines: string[] = ['']
  for (const w of words) {
    const cur = lines[lines.length - 1]
    if (!cur) lines[lines.length - 1] = w
    else if ((cur + ' ' + w).length <= max) lines[lines.length - 1] = cur + ' ' + w
    else lines.push(w)
  }
  if (lines.length > 2) lines.splice(1, lines.length - 1, lines.slice(1).join(' '))
  return lines.map((l) => (l.length > max ? `${l.slice(0, max - 1)}…` : l))
}

/** What a node can do beyond answering, as short chips: the tools that
 * end or leave the call, and where answers come from. */
function chips(node: Agent): string[] {
  const ids = node.tools.map((t) => t.id)
  const out: string[] = []
  if (ids.includes('transfer_to_human')) out.push('→ human')
  if (ids.includes('end_call')) out.push('ends call')
  if (ids.includes('knowledge_lookup') || node.knowledge.length) out.push('knowledge')
  const other = ids.filter((t) => !['transfer_to_human', 'end_call', 'knowledge_lookup'].includes(t))
  if (other.length) out.push(other.length === 1 ? other[0] : `${other.length} tools`)
  return out
}

function flattenWithParent(root: Agent): Agent[] {
  const out: Agent[] = []
  const walk = (node: Agent) => {
    out.push(node)
    node.children.forEach(walk)
  }
  walk(root)
  return out
}

/** agent.id plus every descendant's id — what a drop target must NOT be
 * in, or the move would disconnect that subtree from the root. Mirrors
 * webapi/repository.py's reparent_agent() cycle check, done here only so
 * the UI can skip the confirm() dialog for an obviously invalid drop; the
 * backend is still the real guard (D13). */
function subtreeIds(agent: Agent): Set<string> {
  const ids = new Set<string>()
  const walk = (node: Agent) => {
    ids.add(node.id)
    node.children.forEach(walk)
  }
  walk(agent)
  return ids
}

/** The router level that actually governs this parent->child edge —
 * inspected straight from the agent's own fields, not re-derived by
 * calling the router: eligibility is a Level-1 gate precondition (must
 * pass regardless of what else matches), and then either Level-2 keyword
 * triggers resolve it or, with no triggers at all, only the Level-3 LLM
 * fallback ever would. A child can have both a gate AND triggers — this
 * is why the edge can carry two badges, not one. This is the "render our
 * thesis instead of copying their forward_condition" item from blocco 4. */
function edgeLevels(child: Agent): { gate: boolean; selector: 'pattern' | 'llm' } {
  return { gate: Boolean(child.eligibility), selector: child.triggers.length > 0 ? 'pattern' : 'llm' }
}

export function AgentGraph({ root, selectedId, onSelect, onAddChild, onChanged }: Props) {
  const owner = useOwner()
  const nodes = useMemo(() => (root ? flattenWithParent(root) : []), [root])
  const auto = useMemo(() => (root ? autoLayout(root) : new Map<string, Pos>()), [root])

  const [positions, setPositions] = useState<Map<string, Pos>>(new Map())
  const [search, setSearch] = useState('')
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)
  const dragRef = useRef<{ id: string; dx: number; dy: number; origin: Pos } | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const next = new Map<string, Pos>()
    for (const node of nodes) {
      if (node.layout_x != null && node.layout_y != null) {
        next.set(node.id, { x: node.layout_x, y: node.layout_y })
      } else {
        next.set(node.id, auto.get(node.id) ?? { x: 0, y: 0 })
      }
    }
    setPositions(next)
    // nodes/auto are both derived from `root` — re-run whenever the family
    // itself changes (create/delete/reload), not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root])

  const maxX = Math.max(0, ...[...positions.values()].map((p) => p.x))
  const maxY = Math.max(0, ...[...positions.values()].map((p) => p.y))
  const width = maxX + NODE_W + 24
  const height = maxY + NODE_H + 24

  const matches = (n: Agent) => {
    if (!search.trim()) return true
    const q = search.trim().toLowerCase()
    return n.id.toLowerCase().includes(q) || n.name.toLowerCase().includes(q) || n.description.toLowerCase().includes(q)
  }

  const persistLayout = (id: string, pos: Pos) => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      api.updateAgentLayout(id, { layout_x: pos.x, layout_y: pos.y }).catch(() => {
        // Best-effort: a failed layout save just means the node snaps back
        // to its auto position next reload — never worth surfacing an
        // error banner over where a box sits on screen.
      })
    }, 400)
  }

  const onPointerDown = (e: React.PointerEvent, id: string) => {
    if (!owner) return
    const pos = positions.get(id)
    if (!pos) return
    const svg = (e.target as SVGElement).ownerSVGElement
    const rect = svg?.getBoundingClientRect()
    if (!rect) return
    dragRef.current = { id, dx: e.clientX - rect.left - pos.x, dy: e.clientY - rect.top - pos.y, origin: pos }
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }

  /** The node (if any) a drop at `pos` would reparent `draggedId` onto:
   * whichever other node's box contains the dragged node's center,
   * excluding the dragged node's own subtree (D13's cycle guard) and its
   * current parent (that's just a move, not a reparent). Shared by the
   * hover highlight in onPointerMove and the actual drop in onPointerUp
   * so they never disagree about what's about to happen. */
  const dropTargetFor = (draggedId: string, pos: Pos): Agent | null => {
    const draggedAgent = nodes.find((n) => n.id === draggedId)
    if (!draggedAgent) return null
    const cx = pos.x + NODE_W / 2
    const cy = pos.y + NODE_H / 2
    const forbidden = subtreeIds(draggedAgent)
    const target = nodes.find((n) => {
      if (forbidden.has(n.id)) return false
      const tp = positions.get(n.id)
      return tp && cx >= tp.x && cx <= tp.x + NODE_W && cy >= tp.y && cy <= tp.y + NODE_H
    })
    return target && target.id !== draggedAgent.parent_id ? target : null
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current
    if (!drag) return
    const svg = (e.target as SVGElement).ownerSVGElement
    const rect = svg?.getBoundingClientRect()
    if (!rect) return
    const next = { x: Math.max(0, e.clientX - rect.left - drag.dx), y: Math.max(0, e.clientY - rect.top - drag.dy) }
    setPositions((prev) => new Map(prev).set(drag.id, next))
    setDropTargetId(dropTargetFor(drag.id, next)?.id ?? null)
  }

  /** D13: dropping a node onto another one reparents it there instead of
   * just moving it. Any other drop is a plain layout move, same as
   * before D13. */
  const onPointerUp = () => {
    const drag = dragRef.current
    dragRef.current = null
    setDropTargetId(null)
    if (!drag) return
    const pos = positions.get(drag.id)
    if (!pos) return

    const draggedAgent = nodes.find((n) => n.id === drag.id)
    const target = dropTargetFor(drag.id, pos)

    if (!target || !draggedAgent) {
      persistLayout(drag.id, pos) // no valid drop target — just a layout move
      return
    }

    if (
      !confirm(
        `Move "${draggedAgent.name || draggedAgent.id}" under "${target.name || target.id}"? ` +
          `Its specialists move with it.`,
      )
    ) {
      setPositions((prev) => new Map(prev).set(drag.id, drag.origin))
      return
    }

    api
      .reparentAgent(drag.id, { parent_id: target.id })
      .then(() => onChanged())
      .catch((err) => {
        alert(err instanceof ApiError ? err.message : String(err))
        setPositions((prev) => new Map(prev).set(drag.id, drag.origin))
      })
  }

  const handleDuplicate = async (agent: Agent, e: React.MouseEvent) => {
    e.stopPropagation()
    const newId = prompt(`ID for the copy of "${agent.id}"`, `${agent.id}_copy`)
    if (!newId || !newId.trim()) return
    try {
      await api.createAgent({
        id: newId.trim(),
        parent_id: agent.parent_id,
        name: `${agent.name} (copia)`,
        description: agent.description,
        system_prompt: agent.system_prompt,
        eligibility: agent.eligibility,
        triggers: agent.triggers,
        tools: agent.tools,
        knowledge: agent.knowledge,
        first_message: agent.first_message,
        llm_provider: agent.llm_provider,
        llm_model: agent.llm_model,
        llm_temperature: agent.llm_temperature,
        voice_id: agent.voice_id,
        voice_stability: agent.voice_stability,
        voice_speed: agent.voice_speed,
      })
      onChanged()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : String(err))
    }
  }

  if (!root) {
    return <p className="tree-empty">No agents yet.</p>
  }

  return (
    <div className="agent-graph">
      <div className="agent-graph__toolbar">
        <input
          className="agent-graph__search"
          placeholder="Search agents"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="field-hint">
          {owner ? 'Drag to arrange. Drop an agent on another to move it under that one.' : ''}
        </span>
        {owner && selectedId && (
          <button type="button" className="btn-link" onClick={() => onAddChild(selectedId)}>
            + Add specialist under {nodes.find((n) => n.id === selectedId)?.name || selectedId}
          </button>
        )}
      </div>
      <div className="agent-graph__scroll">
        <svg
          width={width}
          height={height}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
        >
          {/* Edges first, so nodes paint on top. Each is drawn in the
              color of the level that picks the child (pattern if it has
              keywords, LLM otherwise), dashed when a gate rule stands in
              front of it; the labels sit at the child's end, where they
              can't pile up on each other. */}
          {nodes.map((node) =>
            node.children.map((child) => {
              const from = positions.get(node.id)
              const to = positions.get(child.id)
              if (!from || !to) return null
              const levels = edgeLevels(child)
              const x1 = from.x + NODE_W
              const y1 = from.y + NODE_H / 2
              const x2 = to.x
              const y2 = to.y + NODE_H / 2
              const bend = Math.max(40, (x2 - x1) / 2)
              const labels = [...(levels.gate ? ['gate'] : []), levels.selector === 'pattern' ? 'pattern' : 'LLM']
              return (
                <g key={`${node.id}->${child.id}`} className="agent-graph__edge">
                  <path
                    d={`M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`}
                    className={`agent-graph__line agent-graph__line--${levels.selector}${levels.gate ? ' agent-graph__line--gated' : ''}`}
                  />
                  <text x={x2 - 8} y={y2 - 7} className="agent-graph__edge-label">
                    {labels.map((l, i) => (
                      <tspan key={l} className={`agent-graph__edge-label--${l.toLowerCase()}`}>
                        {i > 0 ? ' + ' : ''}
                        {l}
                      </tspan>
                    ))}
                  </text>
                </g>
              )
            }),
          )}

          {nodes.map((node) => {
            const pos = positions.get(node.id)
            if (!pos) return null
            const dimmed = !matches(node)
            return (
              <g
                key={node.id}
                transform={`translate(${pos.x},${pos.y})`}
                className={`agent-graph__node-group${dimmed ? ' agent-graph__node-group--dim' : ''}`}
                onPointerDown={(e) => onPointerDown(e, node.id)}
                onClick={() => onSelect(node.id)}
              >
                <rect
                  width={NODE_W}
                  height={NODE_H}
                  rx={10}
                  className={
                    'agent-graph__node' +
                    (selectedId === node.id ? ' agent-graph__node--selected' : '') +
                    (dropTargetId === node.id ? ' agent-graph__node--drop-target' : '')
                  }
                />
                {(() => {
                  const lines = wrap(node.name || node.id)
                  const sub =
                    node.parent_id === null
                      ? 'Answers first'
                      : node.triggers.length
                        ? `${node.triggers.length} keyword${node.triggers.length === 1 ? '' : 's'}`
                        : 'No keywords'
                  const nodeChips = chips(node)
                  const subY = 19 + lines.length * 15
                  return (
                    <>
                      <title>{node.name || node.id}</title>
                      {lines.map((l, i) => (
                        <text key={i} x={12} y={20 + i * 15} className="agent-graph__node-title">
                          {l}
                        </text>
                      ))}
                      <text x={12} y={subY} className="agent-graph__node-sub">
                        {sub}
                      </text>
                      {nodeChips.reduce<{ x: number; els: React.ReactNode[] }>(
                          (acc, c) => {
                            const w = c.length * 6 + 12
                            if (acc.x + w > NODE_W - 8) return acc
                            acc.els.push(
                              <g key={c} transform={`translate(${acc.x}, ${subY + 7})`}>
                                <rect width={w} height={16} rx={8} className="agent-graph__chip" />
                                <text x={w / 2} y={11.5} textAnchor="middle" className="agent-graph__chip-text">
                                  {c}
                                </text>
                              </g>,
                            )
                            acc.x += w + 4
                            return acc
                          },
                          { x: 12, els: [] },
                      ).els}
                    </>
                  )
                })()}
                {owner && (
                  <g transform={`translate(${NODE_W - 24}, 6)`} onClick={(e) => handleDuplicate(node, e)}>
                    <rect width={18} height={18} rx={4} className="agent-graph__dup-btn" />
                    <text x={9} y={13} textAnchor="middle" className="agent-graph__dup-icon">
                      ⧉
                    </text>
                  </g>
                )}
              </g>
            )
          })}
        </svg>
      </div>
      <ul className="agent-graph__legend" aria-label="Legend">
        <li>
          <svg width="28" height="8" aria-hidden>
            <line x1="0" y1="4" x2="28" y2="4" className="agent-graph__line agent-graph__line--pattern" />
          </svg>
          Pattern: a keyword picks it
        </li>
        <li>
          <svg width="28" height="8" aria-hidden>
            <line x1="0" y1="4" x2="28" y2="4" className="agent-graph__line agent-graph__line--llm" />
          </svg>
          LLM: no keywords, a model picks it
        </li>
        <li>
          <svg width="28" height="8" aria-hidden>
            <line x1="0" y1="4" x2="28" y2="4" className="agent-graph__line agent-graph__line--gated" />
          </svg>
          Gate: a rule decides who can reach it
        </li>
      </ul>
    </div>
  )
}
