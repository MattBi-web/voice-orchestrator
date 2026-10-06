import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CallRecord, CallStats } from '../types'
import { useProjects, useTrees } from '../trees'
import { findAgent } from '../tree'
import { api, ApiError } from '../api'
import { VerdictChip } from './VerdictChip'
import { LEVEL_HEX, LEVELS, SOURCE_LABELS, formatWhen } from './LevelChip'

// One measure per chart, one hue per chart — except routing, where each bar
// *is* a router level and takes that level's color, the same one it has in
// transcripts and on the graph. Light theme only (see index.css).
function useChartPalette() {
  return { series: '#16202e', grid: '#e6e9ee', axis: '#c6cdd6', muted: '#7a8494' }
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function MiniBarChart({
  data,
  xKey,
  yKey,
  palette,
  height = 180,
  colors,
}: {
  data: Record<string, string | number>[]
  xKey: string
  yKey: string
  palette: ReturnType<typeof useChartPalette>
  height?: number
  colors?: string[]
}) {
  if (data.length === 0) {
    return <p className="dashboard__empty">No data yet.</p>
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
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
        <Bar dataKey={yKey} fill={palette.series} radius={[3, 3, 0, 0]} maxBarSize={36}>
          {colors && data.map((_, i) => <Cell key={i} fill={colors[i] ?? palette.series} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function Dashboard({ onOpenCall }: { onOpenCall: (callId: string) => void }) {
  const projects = useProjects()
  const [project, setProject] = useState('')
  const palette = useChartPalette()
  const [stats, setStats] = useState<CallStats | null>(null)
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [includeTest, setIncludeTest] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setError(null)
    Promise.all([api.getCallStats(includeTest, 14, project), api.getCalls(20, project)])
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
  }, [includeTest, project])

  const treesByProject = useTrees(calls.map((c) => c.project_id))
  const projectName = (pid: string) => projects.find((p) => p.id === pid)?.name ?? pid

  const routingData = stats
    ? Object.entries(stats.resolved_by_totals).map(([level, count]) => ({
        level: LEVELS[level]?.label ?? level,
        count,
        color: LEVEL_HEX[level] ?? '#16202e',
      }))
    : []
  const toolData = stats ? Object.entries(stats.tool_totals).map(([tool, count]) => ({ tool, count })) : []
  const dayData = stats ? stats.calls_by_day.map((d) => ({ day: d.date.slice(5), count: d.count })) : []

  return (
    <div className="dashboard">
      <div className="dashboard__toolbar">
        <div className="dashboard__toolbar-actions">
          {projects.length > 1 && (
            <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Agent">
              <option value="">All agents</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <label className="dashboard__toggle">
            <input type="checkbox" checked={includeTest} onChange={(e) => setIncludeTest(e.target.checked)} />
            Include text tests
          </label>
          <button type="button" className="btn-secondary" onClick={load}>
            Refresh
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : stats && stats.total_calls === 0 ? (
        <p className="dashboard__empty">
          No calls yet. Start a call, or send a message from the text test under Agents: every finished call shows
          up here.
        </p>
      ) : (
        <>
          <div className="kpis kpis--5">
            <StatTile label="Calls" value={String(stats?.total_calls ?? 0)} />
            <StatTile label="Minutes" value={(stats?.total_minutes ?? 0).toFixed(1)} />
            <StatTile label="Average length (s)" value={(stats?.avg_duration_seconds ?? 0).toFixed(1)} />
            <StatTile label="Handed over" value={`${((stats?.handoff_rate ?? 0) * 100).toFixed(0)}%`} />
            <StatTile
              label={`Passed (of ${stats?.analyzed_calls ?? 0} evaluated)`}
              value={stats?.success_rate == null ? '—' : `${(stats.success_rate * 100).toFixed(0)}%`}
            />
          </div>

          <div className="dashboard__charts">
            <div className="dashboard__chart-card">
              <h3>Calls per day, last 14 days</h3>
              <MiniBarChart data={dayData} xKey="day" yKey="count" palette={palette} />
            </div>
            <div className="dashboard__chart-card">
              <h3>Turns by router level</h3>
              <MiniBarChart
                data={routingData}
                xKey="level"
                yKey="count"
                palette={palette}
                colors={routingData.map((d) => d.color)}
              />
            </div>
            <div className="dashboard__chart-card">
              <h3>Tool runs</h3>
              <MiniBarChart data={toolData} xKey="tool" yKey="count" palette={palette} />
            </div>
          </div>

          <h3 className="dashboard__table-title">Recent calls</h3>
          <div className="dashboard__table-wrap">
            <table className="dashboard__table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Agent</th>
                  <th>Ended with</th>
                  <th>Length</th>
                  <th>Handovers</th>
                  <th>Evaluation</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.call_id} className="dashboard__row-link" onClick={() => onOpenCall(c.call_id)}>
                    <td>{formatWhen(c.started_at)}</td>
                    <td>
                      <span className={`dashboard__badge dashboard__badge--${c.source}`}>{SOURCE_LABELS[c.source] ?? c.source}</span>
                    </td>
                    <td>{projectName(c.project_id)}</td>
                    <td>
                      {c.final_agent_id
                        ? findAgent(treesByProject[c.project_id] ?? null, c.final_agent_id)?.name || c.final_agent_id
                        : '—'}
                    </td>
                    <td>{c.duration_seconds.toFixed(1)}s</td>
                    <td>{c.handoffs}</td>
                    <td>
                      <VerdictChip verdict={c.call_successful} />
                    </td>
                  </tr>
                ))}
                {calls.length === 0 && (
                  <tr>
                    <td colSpan={7} className="dashboard__empty">
                      No calls to show.
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
