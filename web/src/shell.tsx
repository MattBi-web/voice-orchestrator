import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { Project } from './types'

/** Shell plumbing (redesign): pages put their actions in the top bar, and
 * anything that creates, renames or deletes an agent refreshes the sidebar. */
export const TopbarContext = createContext<HTMLElement | null>(null)

export function TopbarActions({ children }: { children: ReactNode }) {
  const el = useContext(TopbarContext)
  return el ? createPortal(children, el) : null
}

export interface ProjectsState {
  projects: Project[]
  reload: () => void
}

export const ProjectsContext = createContext<ProjectsState>({ projects: [], reload: () => undefined })

export const useProjectsState = () => useContext(ProjectsContext)
