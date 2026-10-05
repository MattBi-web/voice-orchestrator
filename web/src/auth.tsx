import { createContext, useContext } from 'react'

/** Blocco 6: who is looking. `owner` is true when no password is configured
 * (local development) or when the owner is logged in; visitors get a
 * read-only UI. The backend enforces the same rule on every write — this
 * only keeps the UI from offering what would fail with a 401. */
export interface AuthState {
  authRequired: boolean
  owner: boolean
}

export const AuthContext = createContext<AuthState>({ authRequired: false, owner: true })

export const useOwner = () => useContext(AuthContext).owner
