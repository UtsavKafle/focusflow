import type { LucideIcon } from 'lucide-react'
import { BatteryCharging, Footprints, Gauge, Heart, HeartPulse, Moon } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { humanize, num } from '../lib/format'
import { fmtMinutes, fmtTime } from '../lib/time'
import type { StudentState } from '../types'
import { Card, Chip } from './ui'

function Unavailable(props: { reason?: string; large?: boolean }) {
  return (
    <>
      <div className={`font-medium text-muted break-words ${props.large ? 'text-xl' : 'text-lg'}`}>unavailable</div>
      <div className="mt-0.5 text-xs text-secondary">{props.reason ? humanize(props.reason) : 'No reason reported'}</div>
    </>
  )
}

function Tile(props: { label: string; note?: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="neu-tile">
      <div className="flex items-center gap-2 text-xs font-medium text-secondary">
        {props.icon}
        {props.label}
      </div>
      <div className="mt-2">{props.children}</div>
      {props.note && <div className="mt-1.5 text-[11px] text-muted">{props.note}</div>}
    </div>
  )
}

/** Decorative 270-degree dial; the adjacent text always exposes the actual value. */
function Ring(props: { value: number }) {
  const active = Math.round(Math.min(100, Math.max(0, props.value)) / 100 * 40)
  return (
    <svg viewBox="0 0 120 120" className="h-full w-full" aria-hidden>
      {Array.from({ length: 41 }, (_, i) => (
        <line
          key={i}
          x1="60" y1="9" x2="60" y2="16"
          transform={`rotate(${-135 + i * 6.75} 60 60)`}
          stroke={i < active ? 'var(--gauge-active)' : 'var(--gauge-inactive)'}
          strokeWidth="1.7" strokeLinecap="round"
        />
      ))}
    </svg>
  )
}

function Small(props: {
  label: string
  note: string
  icon: LucideIcon
  iconClass: string
  barClass: string
  value: string | null
  unit?: string
  bar?: number | null
  reason?: string
}) {
  const Icon = props.icon
  return (
    <Tile label={props.label} note={props.note} icon={<Icon size={15} className={props.iconClass} aria-hidden />}>
      {props.value === null ? (
        <Unavailable reason={props.reason} />
      ) : (
        <>
          <div className="flex flex-wrap items-baseline gap-1">
            <span className="text-xl font-medium text-ink tabular-nums">{props.value}</span>
            {props.unit && <span className="text-xs text-secondary">{props.unit}</span>}
          </div>
          {typeof props.bar === 'number' && (
            <div className="mt-2 h-1.5 neu-track">
              <div className={`h-1.5 rounded-full ${props.barClass}`} style={{ width: `${Math.min(100, props.bar)}%` }} />
            </div>
          )}
        </>
      )}
    </Tile>
  )
}

const score100 = (v: unknown) => {
  const n = num(v)
  return n === null ? null : Math.round(n * 100)
}

const QUALITY_TONE = { sufficient: 'good', limited: 'alert', unavailable: 'bad' } as const

export function PhysiologyCard(props: { state: StudentState; tz: string }) {
  // Ticks every time a genuinely new state object arrives (the backend only emits state.updated -- and so
  // this component only re-renders with a new `state` -- when the Gold row key or a version actually
  // changes), so this is visible proof a fresh update landed even on a poll where the values it displays
  // happen to be unchanged (e.g. estimated rest only updates once per night).
  const [updatedAt, setUpdatedAt] = useState(() => new Date())
  useEffect(() => {
    setUpdatedAt(new Date())
  }, [props.state])

  const w = props.state.wearable
  const q = w.quality
  const reasons = q.missing_reasons ?? {}
  const hr = num(w.heart_rate_bpm)
  const load = score100(w.physiological_load)
  const activity = score100(w.activity_level)
  const rest = num(w.estimated_rest_minutes)
  const target = num(w.target_rest_minutes)
  const recovery = score100(w.recovery_score)
  const coverage: [string, number | null][] = [
    ['HR', num(q.hr_coverage)],
    ['EDA', num(q.eda_coverage)],
    ['ACC', num(q.acc_coverage)],
    ['Overnight', num(q.overnight_coverage)],
  ]

  return (
    <Card
      id="vitals"
      title="Physiology"
      icon={HeartPulse}
      iconTone="rose"
      subtitle={`${fmtTime(w.window_start, props.tz)} – ${fmtTime(w.window_end, props.tz)} window`}
      right={
        <div className="text-right">
          <Chip tone={QUALITY_TONE[q.status] ?? 'neutral'} title="Signal quality for this window">
            Data quality: {q.status}
          </Chip>
          <div className="mt-1 text-[10px] text-muted" title="Local time this card last received a new state">
            updated {updatedAt.toLocaleTimeString()}
          </div>
        </div>
      }
    >
      <div className="metric-primary">
        <Tile label="Load" note="estimated load, heuristic" icon={<Gauge size={15} className="text-accent" aria-hidden />}>
          {load === null ? (
            <Unavailable large reason={reasons.physiological_load} />
          ) : (
            <div className="metric-gauge relative flex items-center justify-center">
              <div className="absolute inset-0">
                <Ring value={load} />
              </div>
              <div className="text-center leading-none">
                <div className="metric-value text-ink tabular-nums">{load}</div>
                <div className="mt-0.5 text-[10px] text-secondary">of 100</div>
              </div>
            </div>
          )}
        </Tile>

        <Tile
          label="Heart rate"
          icon={
            <Heart
              size={15}
              className={`text-danger ${hr === null ? 'opacity-40' : 'heartbeat'}`}
              // one beat of the animation per real beat
              style={hr === null || hr <= 0 ? undefined : { animationDuration: `${(60 / hr).toFixed(2)}s` }}
              aria-hidden
            />
          }
        >
          {hr === null ? (
            <Unavailable large reason={reasons.heart_rate_bpm} />
          ) : (
            <div className="flex h-30 flex-wrap items-center justify-center gap-1">
              <span className="metric-value text-ink tabular-nums">{hr.toFixed(0)}</span>
              <span className="text-sm text-secondary">bpm</span>
            </div>
          )}
        </Tile>
      </div>

      <div className="metric-secondary">
        <Small
          label="Est. rest"
          note={`not sleep staging${target === null ? '' : ` · target ${fmtMinutes(target)}`}`}
          icon={Moon}
          iconClass="text-accent"
          barClass="bg-accent"
          value={rest === null ? null : fmtMinutes(rest)}
          bar={rest === null || target === null || target <= 0 ? null : (rest / target) * 100}
          reason={reasons.estimated_rest_minutes}
        />
        <Small
          label="Recovery"
          note="heuristic score"
          icon={BatteryCharging}
          iconClass="text-success"
          barClass="bg-success"
          value={recovery === null ? null : String(recovery)}
          unit="/ 100"
          bar={recovery}
          reason={reasons.recovery_score}
        />
        <Small
          label="Activity"
          note="movement level"
          icon={Footprints}
          iconClass="text-accent"
          barClass="bg-muted"
          value={activity === null ? null : String(activity)}
          unit="/ 100"
          bar={activity}
          reason={reasons.activity_level}
        />
      </div>

      <div className="mt-4">
        <div className="mb-1.5 text-xs font-medium text-secondary">Signal coverage</div>
        <dl className="grid grid-cols-4 gap-3">
          {coverage.map(([name, v]) => (
            <div key={name}>
              <div className="flex flex-wrap items-baseline justify-between gap-1 text-[11px]">
                <dt className="text-secondary">{name}</dt>
                <dd className="font-semibold text-ink tabular-nums">{v === null ? 'unknown' : `${Math.round(v * 100)}%`}</dd>
              </div>
              <div className="mt-1 h-1 neu-track">
                {v !== null && <div className="h-1 rounded-full bg-muted" style={{ width: `${v * 100}%` }} />}
              </div>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  )
}
