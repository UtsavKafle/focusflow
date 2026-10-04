// Turns contract blocks into things the week grid can draw.
import type { CalendarBundle, ScheduleBlock, ScheduleChange } from '../types'
import { localParts, ms } from './time'

export type Variant = 'normal' | 'changed' | 'ghost' | 'applied'

export interface GridItem {
  id: string
  blockId?: string
  start: number
  end: number
  title: string
  kind: ScheduleBlock['kind']
  fixedKind?: string
  variant: Variant
  tag?: string
}

export interface Segment {
  item: GridItem
  dayKey: string
  startMin: number
  endMin: number
  lane: 'full' | 'left' | 'right'
}

const ACTION_TAG: Record<string, string> = {
  moved: 'MOVED',
  added: 'NEW',
  removed: 'REMOVED',
  shortened: 'SHORTER',
  extended: 'LONGER',
}

export function blockTitle(block: ScheduleBlock, calendar: CalendarBundle | null): { title: string; fixedKind?: string } {
  switch (block.kind) {
    case 'study': {
      const task = calendar?.tasks.find((t) => t.task_id === block.task_id)
      return { title: task?.title ?? block.task_id ?? 'Study block' }
    }
    case 'fixed': {
      const s = ms(block.start)
      const e = ms(block.end)
      const ev = calendar?.fixed_events.find((f) => ms(f.start) === s && ms(f.end) === e)
      return { title: ev?.title ?? 'Fixed event', fixedKind: ev?.kind }
    }
    case 'sleep_protected':
      return { title: 'Protected sleep' }
    case 'sleep_extension':
      return { title: 'Sleep extension' }
    case 'break':
      return { title: 'Break' }
    default:
      return { title: String(block.kind) }
  }
}

export interface BuildOptions {
  /** Blocks currently in force; ghosts are looked up here in diff mode. */
  previous?: ScheduleBlock[]
  /** Proposal changes: new blocks get highlighted, old positions get ghosted. */
  changes?: ScheduleChange[]
  /** Blocks changed by an already applied decision ("why did this change?"). */
  appliedIds?: Set<string>
}

export function buildItems(blocks: ScheduleBlock[], calendar: CalendarBundle | null, opts: BuildOptions = {}): GridItem[] {
  const items: GridItem[] = []
  const tags = new Map<string, string>()
  for (const c of opts.changes ?? []) {
    for (const id of c.new_block_ids ?? []) tags.set(id, ACTION_TAG[c.action] ?? c.action.toUpperCase())
  }

  const push = (block: ScheduleBlock, variant: Variant, tag?: string) => {
    const start = ms(block.start)
    const end = ms(block.end)
    if (start === null || end === null || end <= start) return
    items.push({
      id: `${variant}:${block.block_id}`,
      blockId: block.block_id,
      start,
      end,
      kind: block.kind,
      variant,
      tag,
      ...blockTitle(block, calendar),
    })
  }

  for (const b of blocks) {
    if (tags.has(b.block_id)) push(b, 'changed', tags.get(b.block_id))
    else if (opts.appliedIds?.has(b.block_id)) push(b, 'applied', 'WHY?')
    else push(b, 'normal')
  }

  // Old positions: blocks named by a change that no longer exist in the proposed plan.
  const present = new Set(blocks.map((b) => b.block_id))
  for (const c of opts.changes ?? []) {
    for (const id of c.old_block_ids ?? []) {
      const old = opts.previous?.find((b) => b.block_id === id)
      if (old && !present.has(id)) push(old, 'ghost', c.action === 'removed' ? 'REMOVED' : 'WAS HERE')
    }
  }

  // Calendar entries the schedule does not carry as blocks (keeps exams visible no matter what).
  const has = (kind: string, s: number, e: number) => items.some((i) => i.kind === kind && i.start === s && i.end === e)
  for (const ev of calendar?.fixed_events ?? []) {
    const s = ms(ev.start)
    const e = ms(ev.end)
    if (s === null || e === null || e <= s || has('fixed', s, e)) continue
    items.push({ id: `cal:${ev.event_id}`, start: s, end: e, title: ev.title, kind: 'fixed', fixedKind: ev.kind, variant: 'normal' })
  }
  for (const [i, iv] of (calendar?.protected_sleep_intervals ?? []).entries()) {
    const s = ms(iv.start)
    const e = ms(iv.end)
    if (s === null || e === null || e <= s || has('sleep_protected', s, e)) continue
    items.push({ id: `cal:sleep-${i}`, start: s, end: e, title: 'Protected sleep', kind: 'sleep_protected', variant: 'normal' })
  }
  return items
}

/** Split items at local midnight and put ghosts beside whatever now occupies their old slot. */
export function toSegments(items: GridItem[], tz: string): Segment[] {
  const segs: Segment[] = []
  for (const item of items) {
    let t = item.start
    for (let i = 0; i < 8 && t < item.end; i++) {
      const { dayKey, minutes } = localParts(t, tz)
      const segEnd = Math.min(item.end, t + (1440 - minutes) * 60_000)
      segs.push({ item, dayKey, startMin: minutes, endMin: minutes + (segEnd - t) / 60_000, lane: 'full' })
      t = segEnd
    }
  }
  for (const g of segs) {
    if (g.item.variant !== 'ghost') continue
    for (const o of segs) {
      if (o.item.variant === 'ghost' || o.dayKey !== g.dayKey) continue
      if (o.startMin < g.endMin && g.startMin < o.endMin) {
        o.lane = 'left'
        g.lane = 'right'
      }
    }
  }
  return segs
}
