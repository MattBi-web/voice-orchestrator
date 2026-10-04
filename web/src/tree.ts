import type { Agent } from './types'

export interface FlatAgent {
  id: string
  name: string
  depth: number
}

/** Depth-first flattening of the tree — used for the "parent" and "start
 * from" dropdowns, where a nested <select> isn't practical but indentation
 * by depth still shows the hierarchy. */
export function flatten(root: Agent | null): FlatAgent[] {
  if (!root) return []
  const out: FlatAgent[] = []
  const walk = (node: Agent, depth: number) => {
    out.push({ id: node.id, name: node.name, depth })
    for (const child of node.children) walk(child, depth + 1)
  }
  walk(root, 0)
  return out
}

export function findAgent(root: Agent | null, id: string): Agent | null {
  if (!root) return null
  if (root.id === id) return root
  for (const child of root.children) {
    const found = findAgent(child, id)
    if (found) return found
  }
  return null
}
