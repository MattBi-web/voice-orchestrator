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

const COL = 250
const ROW = 76
const NODE_W = 200
const NODE_H = 56

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

function truncate(label: string, max = 18): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label
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

const HUMAN_NODE = '__human__'
const END_CALL_NODE = '__end_call__'

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

  const hasHuman = nodes.some((n) => n.tools.some((t) => t.id === 'transfer_to_human'))
  const hasEndCall = nodes.some((n) => n.tools.some((t) => t.id === 'end_call'))

  const maxX = Math.max(0, ...[...positions.values()].map((p) => p.x))
  const virtualX = maxX + COL
  const virtualPositions: Record<string, Pos> = {
    [HUMAN_NODE]: { x: virtualX, y: 0 },
    [END_CALL_NODE]: { x: virtualX, y: ROW * 2 },
  }

  const maxY = Math.max(ROW * 2, ...[...positions.values()].map((p) => p.y))
  const width = virtualX + NODE_W + 40
  const height = maxY + NODE_H + 40

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
        `Spostare "${draggedAgent.name || draggedAgent.id}" sotto "${target.name || target.id}"? ` +
          `Porta con sé tutti i suoi sotto-agenti.`,
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
    const newId = prompt(`Id del duplicato di "${agent.id}"`, `${agent.id}_copy`)
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
          placeholder="cerca per id, nome o descrizione…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="field-hint">
          Trascina i nodi — la posizione si salva da sola. Trascina un nodo sopra un altro per
          cambiargli genitore.
        </span>
        {owner && selectedId && (
          <button type="button" className="btn-link" onClick={() => onAddChild(selectedId)}>
            + figlio di {selectedId}
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
          {/* Edges first, so nodes paint on top */}
          {nodes.map((node) =>
            node.children.map((child) => {
              const from = positions.get(node.id)
              const to = positions.get(child.id)
              if (!from || !to) return null
              const levels = edgeLevels(child)
              const midX = (from.x + NODE_W + to.x) / 2
              const midY = (from.y + to.y) / 2 + NODE_H / 2
              return (
                <g key={`${node.id}->${child.id}`} className="agent-graph__edge">
                  <line
                    x1={from.x + NODE_W}
                    y1={from.y + NODE_H / 2}
                    x2={to.x}
                    y2={to.y + NODE_H / 2}
                    className="agent-graph__line"
                  />
                  {levels.gate && (
                    <text x={midX} y={midY - 8} className="agent-graph__edge-label agent-graph__edge-label--gate">
                      gate
                    </text>
                  )}
                  <text x={midX} y={midY + 8} className="agent-graph__edge-label">
                    {levels.selector === 'pattern' ? 'pattern' : 'LLM fallback'}
                  </text>
                </g>
              )
            }),
          )}

          {hasHuman &&
            nodes
              .filter((n) => n.tools.some((t) => t.id === 'transfer_to_human'))
              .map((n) => {
                const from = positions.get(n.id)
                const to = virtualPositions[HUMAN_NODE]
                if (!from) return null
                return (
                  <line
                    key={`human-${n.id}`}
                    x1={from.x + NODE_W}
                    y1={from.y + NODE_H / 2}
                    x2={to.x}
                    y2={to.y + NODE_H / 2}
                    className="agent-graph__line agent-graph__line--tool"
                  />
                )
              })}
          {hasEndCall &&
            nodes
              .filter((n) => n.tools.some((t) => t.id === 'end_call'))
              .map((n) => {
                const from = positions.get(n.id)
                const to = virtualPositions[END_CALL_NODE]
                if (!from) return null
                return (
                  <line
                    key={`end-${n.id}`}
                    x1={from.x + NODE_W}
                    y1={from.y + NODE_H / 2}
                    x2={to.x}
                    y2={to.y + NODE_H / 2}
                    className="agent-graph__line agent-graph__line--tool"
                  />
                )
              })}

          {hasHuman && (
            <g transform={`translate(${virtualPositions[HUMAN_NODE].x},${virtualPositions[HUMAN_NODE].y})`}>
              <rect width={NODE_W} height={NODE_H} rx={10} className="agent-graph__node agent-graph__node--virtual" />
              <text x={NODE_W / 2} y={NODE_H / 2 + 4} textAnchor="middle" className="agent-graph__node-title">
                👤 Operatore umano
              </text>
            </g>
          )}
          {hasEndCall && (
            <g transform={`translate(${virtualPositions[END_CALL_NODE].x},${virtualPositions[END_CALL_NODE].y})`}>
              <rect width={NODE_W} height={NODE_H} rx={10} className="agent-graph__node agent-graph__node--virtual" />
              <text x={NODE_W / 2} y={NODE_H / 2 + 4} textAnchor="middle" className="agent-graph__node-title">
                📴 Fine chiamata
              </text>
            </g>
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
                <text x={10} y={22} className="agent-graph__node-title">
                  <title>{node.name || node.id}</title>
                  {truncate(node.name || node.id)}
                </text>
                <text x={10} y={40} className="agent-graph__node-sub">
                  {truncate(node.parent_id === null ? 'root' : node.id, 22)}
                </text>
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
    </div>
  )
}
