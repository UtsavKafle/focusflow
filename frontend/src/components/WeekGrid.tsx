import { useMemo } from 'react'
import type { GridItem, Segment } from '../lib/plan'
import { toSegments } from '../lib/plan'
import { dayRange, fmtDayKey, fmtRange, localParts, ms } from '../lib/time'

const HOUR_PX = 28
const HOURS = Array.from({ length: 24 }, (_, h) => h)

function kindClass(item: GridItem): string {
  if (item.variant === 'ghost') return 'ghost-block border-dashed border-slate-500 text-slate-400 line-through'
  switch (item.kind) {
    case 'study':
      return 'bg-sky-500/20 border-sky-400/70 text-sky-50'
    case 'fixed':
      return item.fixedKind === 'exam' || item.fixedKind === 'quiz'
        ? 'bg-rose-500/25 border-rose-400/80 text-rose-50'
        : 'bg-slate-400/20 border-slate-400/60 text-slate-100'
    case 'sleep_protected':
      return 'bg-indigo-500/10 border-indigo-400/25 text-indigo-200'
    case 'sleep_extension':
      return 'bg-emerald-500/25 border-emerald-400/80 text-emerald-50'
    default:
      return 'bg-white/5 border-white/20 text-slate-200'
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
      ? 'ring-2 ring-amber-400 z-10'
      : item.variant === 'applied'
        ? 'ring-2 ring-violet-400 z-10'
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
          className={`ml-1 rounded px-1 text-[9px] font-bold no-underline ${
            item.variant === 'ghost'
              ? 'bg-white/10 text-slate-400'
              : item.variant === 'applied'
                ? 'bg-violet-500 text-white'
                : 'bg-amber-400 text-amber-950'
          }`}
        >
          {item.tag}
        </span>
      )}
      {height >= 34 && <span className="block opacity-80">{fmtRange(item.start, item.end, props.tz)}</span>}
    </>
  )
  const cls = `absolute overflow-hidden rounded border px-1 text-left text-[10px] leading-[12px] ${kindClass(item)} ${highlight}`

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
  onBlockClick?: (blockId: string) => void
}) {
  const { items, tz, asOf } = props
  const segments = useMemo(() => toSegments(items, tz), [items, tz])
  const asOfMs = ms(asOf)
  const now = asOfMs === null ? null : localParts(asOfMs, tz)

  const days = useMemo(() => {
    const keys = segments.map((s) => s.dayKey)
    if (now?.dayKey) keys.push(now.dayKey)
    if (keys.length === 0) return []
    keys.sort()
    return dayRange(keys[0], keys[keys.length - 1])
  }, [segments, now?.dayKey])

  if (days.length === 0) return <p className="text-sm text-slate-400">No plan blocks to show.</p>

  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[560px]" style={{ gridTemplateColumns: `3.25rem repeat(${days.length}, minmax(0, 1fr))` }}>
        <div />
        {days.map((d) => (
          <div
            key={d}
            className={`border-b border-white/10 pb-2 text-center text-xs font-semibold ${
              now?.dayKey === d ? 'text-indigo-300' : 'text-slate-300'
            }`}
          >
            {fmtDayKey(d)}
            {now?.dayKey === d && <span className="ml-1 font-normal">· today in replay</span>}
          </div>
        ))}

        <div className="relative" style={{ height: 24 * HOUR_PX }}>
          {HOURS.filter((h) => h % 2 === 0).map((h) => (
            <div key={h} className="absolute right-1.5 text-[10px] text-slate-500" style={{ top: h * HOUR_PX - 6 }}>
              {h === 0 ? '' : hourLabel(h)}
            </div>
          ))}
        </div>
        {days.map((d) => (
          <div key={d} className="relative border-l border-white/5" style={{ height: 24 * HOUR_PX }}>
            {HOURS.map((h) => (
              <div
                key={h}
                className={`absolute inset-x-0 border-t ${h % 2 === 0 ? 'border-white/5' : 'border-transparent'}`}
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
                className="pointer-events-none absolute inset-x-0 z-20 border-t-2 border-red-500"
                style={{ top: (now.minutes / 60) * HOUR_PX }}
              >
                <span className="absolute -top-3.5 right-0 rounded bg-red-500 px-1 text-[9px] font-bold text-white">
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
      <span className={`inline-block h-3 w-4 rounded border ${cls}`} />
      {text}
    </span>
  )
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">
      {entry('bg-rose-500/25 border-rose-400/80', 'Exam / quiz')}
      {entry('bg-slate-400/20 border-slate-400/60', 'Class')}
      {entry('bg-sky-500/20 border-sky-400/70', 'Study block')}
      {entry('bg-indigo-500/10 border-indigo-400/25', 'Protected sleep')}
      {entry('bg-emerald-500/25 border-emerald-400/80', 'Sleep extension')}
      {entry('ghost-block border-dashed border-slate-500', 'Old position')}
    </div>
  )
}
