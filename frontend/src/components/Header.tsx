import { Activity, Clock, SlidersHorizontal } from 'lucide-react'
import type { SseStatus } from '../hooks/useFocusFlow'
import { MODE_DESCRIPTION, MODE_LABEL, num, SOURCE_LABEL } from '../lib/format'
import { fmtFull } from '../lib/time'
import type { Health, ReplayStatus, StudentState } from '../types'

const MODE_TONE = {
  synthetic_fixture: 'bg-amber-400 text-amber-950',
  live_databricks: 'bg-emerald-400 text-emerald-950',
  saved_replay: 'bg-sky-400 text-sky-950',
}

const SSE_LABEL: Record<SseStatus, { text: string; dot: string }> = {
  connecting: { text: 'Connecting', dot: 'bg-slate-500' },
  open: { text: 'Live', dot: 'bg-emerald-400 live-dot' },
  reconnecting: { text: 'Reconnecting', dot: 'bg-rose-500' },
}

const NAV = [
  ['Vitals', '#vitals'],
  ['Coach', '#coach'],
  ['Plan', '#plan'],
  ['Timeline', '#timeline'],
  ['Tasks', '#tasks'],
]

export const DISCLAIMER =
  'Heuristic estimates from wearable signals. Not medical advice. One adult recording; not validated.'

export function Header(props: {
  health: Health | null
  state: StudentState | null
  replay: ReplayStatus | null
  tz: string
  sse: SseStatus
  onOpenDemo: () => void
}) {
  const { health, state, replay, tz, sse } = props
  const mode = health?.mode
  const modeKnown = mode !== undefined && mode in MODE_LABEL
  const source = state?.source_kind
  const speed = num(replay?.speed)

  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-canvas/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-360 flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-linear-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-500/30">
            <Activity size={20} aria-hidden />
          </span>
          <span className="text-xl font-bold tracking-tight text-white">FocusFlow</span>
        </div>

        <nav className="mr-auto hidden items-center gap-1 lg:flex" aria-label="Sections">
          {NAV.map(([label, href]) => (
            <a
              key={href}
              href={href}
              className="rounded-lg px-2.5 py-1.5 text-sm text-slate-400 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-indigo-400"
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="mr-auto lg:hidden" />

        <div className="flex items-center gap-2 leading-tight">
          <Clock size={16} className="text-slate-500" aria-hidden />
          <div>
            <div className="text-sm font-semibold text-slate-50">{state ? fmtFull(state.as_of, tz) : 'No state yet'}</div>
            <div className="text-[11px] text-slate-400">replay time</div>
          </div>
        </div>

        {/* Mode + data source: always visible, never hidden behind a menu. */}
        <div className="text-right leading-tight" title={health?.label ?? undefined}>
          <span
            className={`inline-block rounded-md px-2.5 py-1 text-xs font-bold tracking-wider ${
              modeKnown ? MODE_TONE[mode] : 'bg-white/10 text-slate-300'
            }`}
          >
            {modeKnown ? MODE_LABEL[mode] : 'MODE UNKNOWN'}
          </span>
          <div className="mt-0.5 text-[11px] text-slate-400">
            {modeKnown ? `${MODE_DESCRIPTION[mode]} · ` : ''}data: {source ? (SOURCE_LABEL[source] ?? source) : 'unknown'}
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400" role="status">
          <span className={`inline-block h-2 w-2 rounded-full ${SSE_LABEL[sse].dot}`} />
          {SSE_LABEL[sse].text}
        </div>

        <button
          type="button"
          onClick={props.onOpenDemo}
          className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm font-medium text-slate-200 transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <SlidersHorizontal size={15} aria-hidden />
          Demo replay
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[11px] font-normal text-slate-300">
            {replay ? `${replay.state}${replay.state === 'running' && speed !== null ? ` ${speed}x` : ''}` : 'status unknown'}
          </span>
        </button>
      </div>
    </header>
  )
}
