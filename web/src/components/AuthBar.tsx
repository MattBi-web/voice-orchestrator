import { useState } from 'react'
import type { AuthState } from '../auth'
import { api, ApiError } from '../api'

/** Blocco 6: login/logout in the header. Renders nothing when no owner
 * password is configured (local development: everyone is the owner). */
export function AuthBar({ auth, onChange }: { auth: AuthState; onChange: (a: AuthState) => void }) {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!auth.authRequired) return null

  const login = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await api.login(password)
      setPassword('')
      setOpen(false)
      onChange({ authRequired: r.auth_required, owner: r.owner })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const logout = async () => {
    const r = await api.logout()
    onChange({ authRequired: r.auth_required, owner: r.owner })
  }

  if (auth.owner) {
    return (
      <div className="auth-bar">
        <span className="auth-bar__who">Signed in as owner</span>
        <button type="button" className="btn-link" onClick={logout}>
          Sign out
        </button>
      </div>
    )
  }

  return (
    <div className="auth-bar">
      {open ? (
        <form className="auth-bar__form" onSubmit={login}>
          <input
            type="password"
            autoFocus
            required
            placeholder="Password"
            aria-label="Owner password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button type="submit" disabled={busy}>
            {busy ? '…' : 'Sign in'}
          </button>
          <button type="button" className="btn-link" onClick={() => setOpen(false)}>
            Cancel
          </button>
          {error && <span className="error auth-bar__error">{error}</span>}
        </form>
      ) : (
        <button type="button" className="btn-secondary" onClick={() => setOpen(true)}>
          Sign in to edit
        </button>
      )}
    </div>
  )
}
