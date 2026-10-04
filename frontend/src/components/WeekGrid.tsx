import { useEffect, useMemo, useRef } from 'react'
import type { GridItem, Segment } from '../lib/plan'
import { toSegments } from '../lib/plan'
import { dayRange, fmtDayKey, fmtRange, localParts, ms } from '../lib/time'

const HOUR_PX = 28
const HOURS = Array.from({ length: 24 }, (_, h) => h)

function kindClass(item: GridItem): string {
  if (item.variant === 'ghost') return 'ghost-block'
  switch (item.kind) {
    case 'study': return 'calendar-block--study'
    case 'fixed': return item.fixedKind === 'exam' || item.fixedKind === 'quiz' ? 'calendar-block--exam' : 'calendar-block--class'
    case 'sleep_protected': return 'calendar-block--sleep'
    case 'sleep_extension': return 'calendar-block--extension'
    default: return ''
  }
}

const hourLabel = (h: number) => (h === 0 ? '12 AM' : h < 12 ? `${h} AM` : h === 12 ? '12 PM' : `${h - 12} PM`)

function Block(props: { seg: Segment; tz: string; onClick?: (blockId: string) => void }) {
  const { seg } = props
  const { item } = seg
  const height = Math.max(11, ((seg.endMin - seg.startMin) / 60) * HOUR_PX - 1)
  const clickable = item.variant === 'applied' && item.blockId !== undefined && props.onClick !== undefined
  const highlight =
    item.variant === 'changed'
      ? 'calendar-block--changed z-10'
      : item.variant === 'applied'
        ? 'calendar-block--applied z-10'
        : ''
  const style = {
    top: (seg.startMin / 60) * HOUR_PX,
    height,
    left: seg.lane === 'right' ? '50%' : 2,
    right: seg.lane === 'left' ? '50%' : 2,
  }
  const label = `${item.title}${item.tag ? ` (${item.tag.toLowerCase()})` : ''}: ${fmtRange(item.start, item.end, props.tz)}`
  const body = (
    <>
      <span className="font-semibold">{item.title}</span>
      {item.tag && (
        <span
          className="calendar-tag ml-1 px-1 text-[9px] font-semibold no-underline"
        >
          {item.tag}
        </span>
      )}
      {height >= 34 && <span className="block">{fmtRange(item.start, item.end, props.tz)}</span>}
    </>
  )
  const cls = `calendar-block absolute overflow-hidden px-1 text-left text-[10px] leading-[12px] ${kindClass(item)} ${highlight}`

  return clickable ? (
    <button
      type="button"
      className={`${cls} cursor-pointer hover:brightness-95`}
      style={style}
      title={`${label}. Click: why did this change?`}
      onClick={() => props.onClick?.(item.blockId as string)}
    >
      {body}
    </button>
  ) : (
    <div className={cls} style={style} title={label}>
      {body}
    </div>
  )
}

export function WeekGrid(props: {
  items: GridItem[]
  tz: string
  asOf: string | null
  running?: boolean
  onBlockClick?: (blockId: string) => void
}) {
  const { items, tz, asOf, running } = props
  const segments = useMemo(() => toSegments(items, tz), [items, tz])
  const asOfMs = ms(asOf)
  const now = asOfMs === null ? null : localParts(asOfMs, tz)
  const nowMarkerRef = useRef<HTMLDivElement>(null)

  // Keep the NOW marker in view as the replay clock advances (HOUR_PX=28 makes the full 24h taller than
  // the visible well, and multi-day weeks make it wider too) -- only while running, so a paused/idle view
  // doesn't yank the scroll position while someone is reading the plan.
  useEffect(() => {
    if (running && nowMarkerRef.current) {
      nowMarkerRef.current.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
    }
  }, [running, now?.dayKey, now?.minutes])

  const days = useMemo(() => {
    const keys = segments.map((s) => s.dayKey)
    if (now?.dayKey) keys.push(now.dayKey)
    if (keys.length === 0) return []
    keys.sort()
    return dayRange(keys[0], keys[keys.length - 1])
  }, [segments, now?.dayKey])

  if (days.length === 0) return <p className="text-sm text-secondary">No plan blocks to show.</p>

  return (
    <div
      className="calendar-well max-h-[520px] overflow-y-auto"
      role="region"
      aria-label="Weekly calendar, scroll for the full 24 hours and more days"
      tabIndex={0}
    >
      <div className="grid min-w-[560px]" style={{ gridTemplateColumns: `3.25rem repeat(${days.length}, minmax(0, 1fr))` }}>
        <div />
        {days.map((d) => (
          <div
            key={d}
            className={`border-b border-separator pb-2 text-center text-xs font-semibold ${
              now?.dayKey === d ? 'text-accent' : 'text-secondary'
            }`}
          >
            {fmtDayKey(d)}
            {now?.dayKey === d && <span className="ml-1 font-normal">· today in replay</span>}
          </div>
        ))}

        <div className="relative" style={{ height: 24 * HOUR_PX }}>
          {HOURS.filter((h) => h % 2 === 0).map((h) => (
            <div key={h} className="absolute right-1.5 text-[10px] text-muted" style={{ top: h * HOUR_PX - 6 }}>
              {h === 0 ? '' : hourLabel(h)}
            </div>
          ))}
        </div>
        {days.map((d) => (
          <div key={d} className="relative border-l border-separator" style={{ height: 24 * HOUR_PX }}>
            {HOURS.map((h) => (
              <div
                key={h}
                className={`absolute inset-x-0 border-t ${h % 2 === 0 ? 'border-separator' : 'border-transparent'}`}
                style={{ top: h * HOUR_PX }}
              />
            ))}
            {segments
              .filter((s) => s.dayKey === d)
              .map((s) => (
                <Block key={`${s.item.id}:${s.startMin}`} seg={s} tz={tz} onClick={props.onBlockClick} />
              ))}
            {now?.dayKey === d && (
              <div
                ref={nowMarkerRef}
                className="pointer-events-none absolute inset-x-0 z-20 border-t-2 border-danger"
                style={{ top: (now.minutes / 60) * HOUR_PX }}
              >
                <span className="absolute -top-3.5 right-0 rounded bg-danger px-1 text-[9px] font-semibold text-panel">
                  NOW
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function PlanLegend() {
  const entry = (cls: string, text: string) => (
    <span className="inline-flex items-center gap-1">
      <span className={`calendar-block inline-block h-3 w-4 ${cls}`} />
      {text}
    </span>
  )
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-secondary">
      {entry('calendar-block--exam', 'Exam / quiz')}
      {entry('calendar-block--class', 'Class')}
      {entry('calendar-block--study', 'Study block')}
      {entry('calendar-block--sleep', 'Protected sleep')}
      {entry('calendar-block--extension', 'Sleep extension')}
      {entry('ghost-block', 'Old position')}
    </div>
  )
}
