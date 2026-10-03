import type { LucideIcon } from 'lucide-react'
import { BatteryCharging, Footprints, Gauge, Heart, HeartPulse, Moon } from 'lucide-react'
import type { ReactNode } from 'react'
import { humanize, num } from '../lib/format'
import { fmtMinutes, fmtTime } from '../lib/time'
import type { StudentState } from '../types'
import { Card, Chip } from './ui'

function Unavailable(props: { reason?: string; large?: boolean }) {
  return (
    <>
      <div className={`font-semibold text-slate-500 ${props.large ? 'text-2xl' : 'text-lg'}`}>unavailable</div>
      <div className="mt-0.5 text-xs text-slate-400">{props.reason ? humanize(props.reason) : 'No reason reported'}</div>
    </>
  )
}

function Tile(props: { label: string; note?: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-xl bg-white/5 p-3.5 ring-1 ring-white/5">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-300">
        {props.icon}
        {props.label}
      </div>
      <div className="mt-2">{props.children}</div>
      {props.note && <div className="mt-1.5 text-[11px] text-slate-500">{props.note}</div>}
    </div>
  )
}

/** 0-100 ring. Decorative emphasis only: the number in the middle is the value. */
function Ring(props: { value: number }) {
  const r = 34
  const c = 2 * Math.PI * r
  return (
    <svg viewBox="0 0 84 84" className="h-24 w-24 -rotate-90" aria-hidden>
      <defs>
        <linearGradient id="ring-load" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#818cf8" />
          <stop offset="100%" stopColor="#c084fc" />
        </linearGradient>
      </defs>
      <circle cx="42" cy="42" r={r} fill="none" stroke="rgb(255 255 255 / 0.08)" strokeWidth="8" />
      <circle
        cx="42"
        cy="42"
        r={r}
        fill="none"
        stroke="url(#ring-load)"
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={`${(props.value / 100) * c} ${c}`}
      />
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
          <div className="flex items-baseline gap-1">
            <span className="text-xl font-semibold whitespace-nowrap text-slate-50 tabular-nums">{props.value}</span>
            {props.unit && <span className="text-xs text-slate-400">{props.unit}</span>}
          </div>
          {typeof props.bar === 'number' && (
            <div className="mt-2 h-1.5 rounded-full bg-white/10">
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
        <Chip tone={QUALITY_TONE[q.status] ?? 'neutral'} title="Signal quality for this window">
          Data quality: {q.status}
        </Chip>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Tile label="Load" note="estimated load, heuristic" icon={<Gauge size={15} className="text-indigo-300" aria-hidden />}>
          {load === null ? (
            <Unavailable large reason={reasons.physiological_load} />
          ) : (
            <div className="relative flex h-24 w-24 items-center justify-center">
              <div className="absolute inset-0">
                <Ring value={load} />
              </div>
              <div className="text-center leading-none">
                <div className="text-3xl font-semibold text-slate-50 tabular-nums">{load}</div>
                <div className="mt-0.5 text-[10px] text-slate-400">of 100</div>
              </div>
            </div>
          )}
        </Tile>

        <Tile
          label="Heart rate"
          icon={
            <Heart
              size={15}
              className={`fill-rose-500 text-rose-500 ${hr === null ? 'opacity-40' : 'heartbeat'}`}
              // one beat of the animation per real beat
              style={hr === null || hr <= 0 ? undefined : { animationDuration: `${(60 / hr).toFixed(2)}s` }}
              aria-hidden
            />
          }
        >
          {hr === null ? (
            <Unavailable large reason={reasons.heart_rate_bpm} />
          ) : (
            <div className="flex h-24 items-center gap-2">
              <span className="text-5xl font-semibold text-slate-50 tabular-nums">{hr.toFixed(0)}</span>
              <span className="text-sm text-slate-400">bpm</span>
            </div>
          )}
        </Tile>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3">
        <Small
          label="Est. rest"
          note={`not sleep staging${target === null ? '' : ` · target ${fmtMinutes(target)}`}`}
          icon={Moon}
          iconClass="text-violet-300"
          barClass="bg-violet-400"
          value={rest === null ? null : fmtMinutes(rest)}
          bar={rest === null || target === null || target <= 0 ? null : (rest / target) * 100}
          reason={reasons.estimated_rest_minutes}
        />
        <Small
          label="Recovery"
          note="heuristic score"
          icon={BatteryCharging}
          iconClass="text-emerald-300"
          barClass="bg-emerald-400"
          value={recovery === null ? null : String(recovery)}
          unit="/ 100"
          bar={recovery}
          reason={reasons.recovery_score}
        />
        <Small
          label="Activity"
          note="movement level"
          icon={Footprints}
          iconClass="text-sky-300"
          barClass="bg-sky-400"
          value={activity === null ? null : String(activity)}
          unit="/ 100"
          bar={activity}
          reason={reasons.activity_level}
        />
      </div>

      <div className="mt-4">
        <div className="mb-1.5 text-xs font-medium text-slate-400">Signal coverage</div>
        <dl className="grid grid-cols-4 gap-3">
          {coverage.map(([name, v]) => (
            <div key={name}>
              <div className="flex items-baseline justify-between text-[11px]">
                <dt className="text-slate-400">{name}</dt>
                <dd className="font-semibold text-slate-200 tabular-nums">{v === null ? 'unknown' : `${Math.round(v * 100)}%`}</dd>
              </div>
              <div className="mt-1 h-1 rounded-full bg-white/10">
                {v !== null && <div className="h-1 rounded-full bg-slate-400" style={{ width: `${v * 100}%` }} />}
              </div>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  )
}
