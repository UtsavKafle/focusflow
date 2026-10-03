import { LineChart as LineChartIcon } from 'lucide-react'
import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AppliedDecision } from '../hooks/useFocusFlow'
import { num, SOURCE_LABEL } from '../lib/format'
import { fmtTime, ms } from '../lib/time'
import type { HistoryResponse } from '../types'
import { Card } from './ui'

// Dark-mode steps of categorical slots 1 and 2 (validated as a pair against the panel surface).
const C_LOAD = '#3987e5'
const C_ACTIVITY = '#d95926'
// One series on its own chart: the heart-rate line wears the same rose as the heart icon.
const C_HR = '#fb7185'
const INK = '#94a3b8'
const GRID = '#263042'
const SURFACE = '#141a26'

interface Row {
  t: number
  hr: number | null
  load: number | null
  activity: number | null
}

interface Marker {
  t: number
  label: string
  color: string
  dashed: boolean
}

function buildRows(history: HistoryResponse | null): Row[] {
  const rows: Row[] = []
  for (const w of history?.windows ?? []) {
    const t = ms(w.window_end)
    if (t === null) continue
    const load = num(w.physiological_load)
    const activity = num(w.activity_level)
    rows.push({
      t,
      hr: num(w.heart_rate_bpm),
      load: load === null ? null : Math.round(load * 100),
      activity: activity === null ? null : Math.round(activity * 100),
    })
  }
  rows.sort((a, b) => a.t - b.t)
  // Windows that are missing entirely must also break the line, not be bridged.
  const out: Row[] = []
  for (const [i, r] of rows.entries()) {
    if (i > 0 && r.t - rows[i - 1].t > 90_000) out.push({ t: rows[i - 1].t + 60_000, hr: null, load: null, activity: null })
    out.push(r)
  }
  return out
}

/** Stretches of time where no wearable value is available at all. */
function gapRuns(rows: Row[]): [number, number][] {
  const runs: [number, number][] = []
  let start: number | null = null
  for (const [i, r] of rows.entries()) {
    const empty = r.hr === null && r.load === null
    if (empty && start === null) start = i > 0 ? rows[i - 1].t : r.t
    if (!empty && start !== null) {
      runs.push([start, r.t])
      start = null
    }
  }
  if (start !== null && rows.length > 0) runs.push([start, rows[rows.length - 1].t])
  return runs
}

function Tip(props: { active?: boolean; label?: number | string; payload?: readonly { name?: unknown; dataKey?: unknown; color?: string; payload?: Row }[]; tz: string; unit: string }) {
  const row = props.payload?.[0]?.payload
  if (!props.active || !row) return null
  return (
    <div className="rounded-lg border border-white/10 bg-canvas px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-semibold text-slate-50">{fmtTime(row.t, props.tz)}</div>
      {(props.payload ?? []).map((p) => {
        const v = row[p.dataKey as keyof Row]
        return (
          <div key={String(p.dataKey)} className="flex items-center gap-1.5 text-slate-300">
            <span className="inline-block h-0.5 w-3" style={{ background: p.color }} />
            {String(p.name)}: <span className="font-medium">{v === null ? 'unavailable' : `${v}${props.unit}`}</span>
          </div>
        )
      })}
    </div>
  )
}

export function Timeline(props: {
  history: HistoryResponse | null
  tz: string
  asOf: string | null
  evidenceIds: string[]
  decisions: AppliedDecision[]
}) {
  const { history, tz } = props
  const rows = useMemo(() => buildRows(history), [history])
  const gaps = useMemo(() => gapRuns(rows), [rows])

  const markers = useMemo(() => {
    const out: Marker[] = []
    const lo = rows[0]?.t ?? 0
    const hi = rows[rows.length - 1]?.t ?? 0
    const evidence = new Set(props.evidenceIds)
    for (const w of history?.windows ?? []) {
      const t = ms(w.window_end)
      if (t !== null && w.evidence_id && evidence.has(w.evidence_id)) out.push({ t, label: 'evidence', color: '#9085e9', dashed: true })
    }
    for (const d of props.decisions) {
      const t = ms(d.appliedAsOf)
      if (t !== null) out.push({ t, label: 'plan changed', color: '#f8fafc', dashed: false })
    }
    // Cited windows are often adjacent minutes: label only the first marker of each kind.
    const labelled = new Set<string>()
    return out
      .filter((m) => m.t >= lo && m.t <= hi)
      .sort((a, b) => a.t - b.t)
      .map((m) => {
        const first = !labelled.has(m.label)
        labelled.add(m.label)
        return first ? m : { ...m, label: '' }
      })
  }, [history, rows, props.evidenceIds, props.decisions])

  const domain: [number, number] | undefined = rows.length > 0 ? [rows[0].t, rows[rows.length - 1].t] : undefined

  const axis = (
    <XAxis
      dataKey="t"
      type="number"
      scale="time"
      domain={domain}
      tickFormatter={(t: number) => fmtTime(t, tz)}
      tick={{ fontSize: 11, fill: INK }}
      stroke={GRID}
      minTickGap={48}
    />
  )
  const overlays = (
    <>
      {gaps.map(([a, b]) => (
        <ReferenceArea key={`g${a}`} x1={a} x2={b} fill="#94a3b8" fillOpacity={0.14} stroke="none" />
      ))}
      {markers.map((m, i) => (
        <ReferenceLine
          key={`m${i}`}
          x={m.t}
          stroke={m.color}
          strokeDasharray={m.dashed ? '4 3' : undefined}
          strokeWidth={1.5}
          label={m.label ? { value: m.label, position: m.dashed ? 'insideTopRight' : 'insideBottomRight', fontSize: 10, fill: INK } : undefined}
        />
      ))}
    </>
  )
  const line = (key: keyof Row, name: string, color: string) => (
    <Line
      dataKey={key}
      name={name}
      type="monotone"
      stroke={color}
      strokeWidth={2}
      dot={false}
      activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2 }}
      connectNulls={false}
      isAnimationActive={false}
    />
  )

  return (
    <Card
      id="timeline"
      icon={LineChartIcon}
      iconTone="emerald"
      title="Wearable timeline"
      subtitle={`One-minute windows up to replay time · ${history?.source_kind ? (SOURCE_LABEL[history.source_kind] ?? history.source_kind) : 'unknown'}`}
    >
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400">No wearable history is available for this run yet.</p>
      ) : (
        <div className="space-y-1">
          <div className="text-xs font-medium text-slate-400">Estimated load and activity (0 to 100, heuristic)</div>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} syncId="wearable" margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                {axis}
                <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tick={{ fontSize: 11, fill: INK }} stroke={GRID} />
                <Tooltip content={(p) => <Tip {...p} tz={tz} unit="" />} />
                <Legend verticalAlign="top" align="right" height={22} iconType="plainline" wrapperStyle={{ fontSize: 11 }} formatter={(v) => <span style={{ color: INK }}>{v}</span>} />
                {overlays}
                {line('load', 'Estimated load', C_LOAD)}
                {line('activity', 'Activity', C_ACTIVITY)}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="pt-2 text-xs font-medium text-slate-400">Heart rate (bpm)</div>
          <div className="h-36">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} syncId="wearable" margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                {axis}
                <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11, fill: INK }} stroke={GRID} />
                <Tooltip content={(p) => <Tip {...p} tz={tz} unit=" bpm" />} />
                {overlays}
                {line('hr', 'Heart rate', C_HR)}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-slate-400">
            Shaded bands mean heart rate and load are unavailable for that period; a break in a line means no valid value. Nothing is interpolated.
            {markers.length > 0 && ' Dashed lines mark evidence the coach cited; solid lines mark applied plan changes.'}
          </p>
        </div>
      )}
    </Card>
  )
}
