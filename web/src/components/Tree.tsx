import type { Agent } from '../types'
import { useOwner } from '../auth'

interface Props {
  root: Agent | null
  selectedId: string | null
  onSelect: (id: string) => void
  onAddChild: (parentId: string) => void
}

function TreeNode({
  node,
  depth,
  selectedId,
  onSelect,
  onAddChild,
}: {
  node: Agent
  depth: number
} & Pick<Props, 'selectedId' | 'onSelect' | 'onAddChild'>) {
  const owner = useOwner()
  return (
    <div>
      <div
        className={`tree-row${selectedId === node.id ? ' tree-row--selected' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button className="tree-row__label" onClick={() => onSelect(node.id)}>
          {node.name || node.id}
          {node.eligibility && <span className="tree-row__badge" title={node.eligibility}>gated</span>}
        </button>
        {owner && (<button
          className="tree-row__add"
          title={`Add a child of ${node.id}`}
          onClick={() => onAddChild(node.id)}
        >
          +
        </button>)}
      </div>
      {node.children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
          onAddChild={onAddChild}
        />
      ))}
    </div>
  )
}

export function Tree({ root, selectedId, onSelect, onAddChild }: Props) {
  if (!root) {
    return <p className="tree-empty">No agents yet.</p>
  }
  return (
    <div className="tree">
      <TreeNode node={root} depth={0} selectedId={selectedId} onSelect={onSelect} onAddChild={onAddChild} />
    </div>
  )
}
