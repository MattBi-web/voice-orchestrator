import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CallRecord, CallStats } from '../types'
import { api, ApiError } from '../api'

// This project's single-series bar charts all carry one measure broken out
// by a nominal category (day, routing level, tool, or source) — per the
// data-viz method, that's "one series, one color," never a rainbow across
// bars that would just double-encode the bar's own length as hue. One hue
// (categorical slot 1, light/dark stepped) is all four charts below need.
function useChartPalette() {
  const [dark, setDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return dark
    ? { series: '#3987e5', grid: '#2c2c2a', axis: '#383835', muted: '#898781' }
    : { series: '#2a78d6', grid: '#e1e0d9', axis: '#c3c2b7', muted: '#898781' }
}

const RESOLVED_BY_LABELS: Record<string, string> = {
  gate_only: 'solo gate',
  pattern: 'pattern',
  llm_fallback: 'LLM fallback',
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-tile">
      <div className="stat-tile__value">{value}</div>
      <div className="stat-tile__label">{label}</div>
    </div>
  )
}

function MiniBarChart({
  data,
  xKey,
  yKey,
  palette,
  height = 180,
}: {
  data: Record<string, string | number>[]
  xKey: string
  yKey: string
  palette: ReturnType<typeof useChartPalette>
  height?: number
}) {
  if (data.length === 0) {
    return <p className="dashboard__empty">Ancora nessun dato.</p>
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={palette.grid} />
        <XAxis
          dataKey={xKey}
          tick={{ fill: palette.muted, fontSize: 11 }}
          axisLine={{ stroke: palette.axis }}
          tickLine={false}
        />
        <YAxis tick={{ fill: palette.muted, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} width={28} />
        <Tooltip
          cursor={{ fill: palette.grid }}
          contentStyle={{ background: 'var(--bg)', border: `1px solid ${palette.grid}`, borderRadius: 6, fontSize: 12 }}
        />
        <Bar dataKey={yKey} fill={palette.series} radius={[4, 4, 0, 0]} maxBarSize={36} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function Dashboard() {
  const palette = useChartPalette()
  const [stats, setStats] = useState<CallStats | null>(null)
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [includeTest, setIncludeTest] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setError(null)
    Promise.all([api.getCallStats(includeTest), api.getCalls(20)])
      .then(([s, c]) => {
        setStats(s)
        setCalls(c.calls)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeTest])

  const routingData = stats
    ? Object.entries(stats.resolved_by_totals).map(([level, count]) => ({
        level: RESOLVED_BY_LABELS[level] ?? level,
        count,
      }))
    : []
  const toolData = stats ? Object.entries(stats.tool_totals).map(([tool, count]) => ({ tool, count })) : []
  const dayData = stats ? stats.calls_by_day.map((d) => ({ day: d.date.slice(5), count: d.count })) : []

  return (
    <div className="dashboard">
      <div className="dashboard__toolbar">
        <h2>Dashboard chiamate</h2>
        <div className="dashboard__toolbar-actions">
          <label className="dashboard__toggle">
            <input type="checkbox" checked={includeTest} onChange={(e) => setIncludeTest(e.target.checked)} />
            Includi i test da "Agent builder"
          </label>
          <button type="button" className="btn-secondary" onClick={load}>
            Aggiorna
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : stats && stats.total_calls === 0 ? (
        <p className="dashboard__empty">
          Nessuna chiamata registrata ancora. Prova qualcosa nel box "Agent builder", o fai una chiamata vera dalla tab
          "Test live (voce)" — ogni chiamata finita finisce qui.
        </p>
      ) : (
        <>
          <div className="dashboard__tiles">
            <StatTile label="Chiamate totali" value={String(stats?.total_calls ?? 0)} />
            <StatTile label="Minuti totali" value={(stats?.total_minutes ?? 0).toFixed(1)} />
            <StatTile label="Durata media (s)" value={(stats?.avg_duration_seconds ?? 0).toFixed(1)} />
            <StatTile label="Handoff rate" value={`${((stats?.handoff_rate ?? 0) * 100).toFixed(0)}%`} />
          </div>

          <div className="dashboard__charts">
            <div className="dashboard__chart-card">
              <h3>Chiamate per giorno (14gg)</h3>
              <MiniBarChart data={dayData} xKey="day" yKey="count" palette={palette} />
            </div>
            <div className="dashboard__chart-card">
              <h3>Instradamento per livello</h3>
              <MiniBarChart data={routingData} xKey="level" yKey="count" palette={palette} />
            </div>
            <div className="dashboard__chart-card">
              <h3>Utilizzo tool</h3>
              <MiniBarChart data={toolData} xKey="tool" yKey="count" palette={palette} />
            </div>
          </div>

          <h3 className="dashboard__table-title">Chiamate recenti</h3>
          <div className="dashboard__table-wrap">
            <table className="dashboard__table">
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Fonte</th>
                  <th>Canale</th>
                  <th>Agente finale</th>
                  <th>Durata</th>
                  <th>Handoff</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.call_id}>
                    <td>{new Date(c.started_at).toLocaleString('it-IT')}</td>
                    <td>
                      <span className={`dashboard__badge dashboard__badge--${c.source}`}>{c.source}</span>
                    </td>
                    <td>{c.channel}</td>
                    <td>{c.final_agent_id ?? '—'}</td>
                    <td>{c.duration_seconds.toFixed(1)}s</td>
                    <td>{c.handoffs}</td>
                  </tr>
                ))}
                {calls.length === 0 && (
                  <tr>
                    <td colSpan={6} className="dashboard__empty">
                      Nessuna chiamata da mostrare.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
