import { Activity, Clock, SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { SseStatus } from '../hooks/useFocusFlow'
import { MODE_DESCRIPTION, MODE_LABEL, num, SOURCE_LABEL } from '../lib/format'
import { fmtFull } from '../lib/time'
import type { Health, ReplayStatus, StudentState } from '../types'
import { GlassSurface } from './ui'

const MODE_TONE = {
  synthetic_fixture: 'text-warning',
  live_databricks: 'text-success',
  saved_replay: 'text-accent',
}

const SSE_LABEL: Record<SseStatus, { text: string; dot: string }> = {
  connecting: { text: 'Connecting', dot: 'bg-muted' },
  open: { text: 'Live', dot: 'bg-success live-dot' },
  reconnecting: { text: 'Reconnecting', dot: 'bg-danger' },
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
  const [section, setSection] = useState('#vitals')

  useEffect(() => {
    const syncSection = () => setSection(window.location.hash || '#vitals')
    syncSection()
    window.addEventListener('hashchange', syncSection)
    return () => window.removeEventListener('hashchange', syncSection)
  }, [])

  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="header-brand flex items-center gap-2.5">
          <span className="neu-icon brand-orb">
            <Activity size={20} aria-hidden />
          </span>
          <span className="text-xl font-semibold tracking-tight text-ink">!Presh</span>
        </div>

        <nav className="glass-toolbar mr-auto hidden items-center gap-1 lg:flex" aria-label="Sections">
          {NAV.map(([label, href]) => (
            <a
              key={href}
              href={href}
              className="nav-link"
              aria-current={section === href ? 'location' : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="header-spacer mr-auto lg:hidden" />

        <div className="header-clock flex items-center gap-2 leading-tight">
          <Clock size={16} className="text-muted" aria-hidden />
          <div>
            <div className="text-sm font-semibold text-ink">{state ? fmtFull(state.as_of, tz) : 'No state yet'}</div>
            <div className="text-[11px] text-secondary">replay time</div>
          </div>
        </div>

        {/* Mode + data source: always visible, never hidden behind a menu. */}
        <div className="header-source text-right leading-tight" title={health?.label ?? undefined}>
          <GlassSurface variant="clear" className={`mode-badge ${modeKnown ? MODE_TONE[mode] : 'text-secondary'}`}>
            {modeKnown ? MODE_LABEL[mode] : 'MODE UNKNOWN'}
          </GlassSurface>
          <div className="mt-0.5 text-[11px] text-secondary">
            <span className="source-description">{modeKnown ? `${MODE_DESCRIPTION[mode]} · ` : ''}</span>data: {source ? (SOURCE_LABEL[source] ?? source) : 'unknown'}
          </div>
        </div>

        <div className="header-status flex items-center gap-2 text-xs text-secondary" role="status">
          <span className={`inline-block h-2 w-2 rounded-full ${SSE_LABEL[sse].dot}`} />
          {SSE_LABEL[sse].text}
        </div>

        <button
          type="button"
          onClick={props.onOpenDemo}
          className="header-demo neu-button glass-button"
        >
          <SlidersHorizontal size={15} aria-hidden />
          Demo replay
          <span className="replay-state rounded neu-inset px-1.5 py-0.5 text-[11px] font-normal text-secondary">
            {replay ? `${replay.state}${replay.state === 'running' && speed !== null ? ` ${speed}x` : ''}` : 'status unknown'}
          </span>
        </button>
      </div>
    </header>
  )
}
