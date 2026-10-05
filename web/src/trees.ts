import { useEffect, useState } from 'react'
import type { Agent, Project } from './types'
import { api } from './api'

/** Blocco 8: agent trees and project names for pages that span projects
 * (Calls, Analytics), fetched once per project and shared. */
const trees = new Map<string, Promise<Agent | null>>()

export function loadTree(pid: string): Promise<Agent | null> {
  let t = trees.get(pid)
  if (!t) {
    t = api
      .getTree(pid)
      .then((r) => r.root)
      .catch(() => null)
    trees.set(pid, t)
  }
  return t
}

export function forgetTrees() {
  trees.clear()
}

export function useTrees(pids: string[]): Record<string, Agent | null> {
  const [out, setOut] = useState<Record<string, Agent | null>>({})
  const key = [...new Set(pids)].sort().join('|')
  useEffect(() => {
    let live = true
    Promise.all(key ? key.split('|').map((p) => loadTree(p).then((t) => [p, t] as const)) : []).then((pairs) => {
      if (live) setOut(Object.fromEntries(pairs))
    })
    return () => {
      live = false
    }
  }, [key])
  return out
}

export function useProjects(): Project[] {
  const [list, setList] = useState<Project[]>([])
  useEffect(() => {
    api
      .listProjects()
      .then((r) => setList(r.projects))
      .catch(() => setList([]))
  }, [])
  return list
}
