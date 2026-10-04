import { CalendarDays } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { FocusFlow } from '../hooks/useFocusFlow'
import { reasonLabel } from '../lib/format'
import { blockTitle, buildItems } from '../lib/plan'
import { fmtDayTime, fmtMinutes, fmtRange } from '../lib/time'
import type { CalendarBundle, ScheduleBlock, ScheduleChange, UnscheduledWork } from '../types'
import { Button, Card, Chip, Label } from './ui'
import { PlanLegend, WeekGrid } from './WeekGrid'

function UnscheduledList(props: { work: UnscheduledWork[]; calendar: CalendarBundle | null; tz: string; proposed: boolean }) {
  if (props.work.length === 0) return null
  return (
    <div className="rounded-xl neu-notice neu-notice--error p-4" role="alert">
      <div className="text-sm font-semibold text-danger">
        {props.proposed ? 'Not everything fits: work left unscheduled' : 'Unscheduled work in the current plan'}
      </div>
      <ul className="mt-1.5 space-y-1 text-sm text-danger">
        {props.work.map((u) => (
          <li key={`${u.task_id}:${u.deadline}`}>
            <span className="font-semibold">
              {props.calendar?.tasks.find((t) => t.task_id === u.task_id)?.title ?? u.task_id}
            </span>
            : {fmtMinutes(u.minutes)} cannot be placed before {fmtDayTime(u.deadline, props.tz)}.{' '}
            <span className="text-danger">{reasonLabel(u.reason)}.</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChangeList(props: {
  changes: ScheduleChange[]
  before: ScheduleBlock[]
  after: ScheduleBlock[]
  calendar: CalendarBundle | null
  tz: string
}) {
  const { changes, before, after, calendar, tz } = props
  if (changes.length === 0) return <p className="text-sm text-secondary">The proposal keeps the plan as it is.</p>
  const describe = (ids: string[] | undefined, pool: ScheduleBlock[]) =>
    (ids ?? [])
      .map((id) => pool.find((b) => b.block_id === id))
      .filter((b): b is ScheduleBlock => b !== undefined)
  return (
    <ul className="space-y-4 text-sm">
      {changes.map((c) => {
        const olds = describe(c.old_block_ids, before)
        const news = describe(c.new_block_ids, after)
        const title = blockTitle(news[0] ?? olds[0] ?? ({ kind: 'study', block_id: '', start: '', end: '' } as ScheduleBlock), calendar).title
        return (
          <li key={c.change_id} className="neu-list-item">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="alert">{c.action}</Chip>
              <span className="font-semibold text-ink">{title}</span>
              <span className="text-xs text-secondary">{reasonLabel(c.reason_code)}</span>
            </div>
            <div className="mt-1 text-xs text-secondary">
              {olds.length > 0 && (
                <span className="text-secondary line-through">
                  {olds.map((b) => fmtRange(b.start, b.end, tz)).join(', ')}
                </span>
              )}
              {olds.length > 0 && news.length > 0 && <span className="mx-1.5">→</span>}
              {news.length > 0 && (
                <span className="font-medium">{news.map((b) => fmtRange(b.start, b.end, tz)).join(', ')}</span>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function PlanCard(props: { ff: FocusFlow; tz: string; onWhy: (blockId: string) => void }) {
  const { ff, tz } = props
  const { schedule, calendar, job, state, decisions } = ff
  const proposal = job?.status === 'ready' ? (job.proposal ?? null) : null
  const [showCurrent, setShowCurrent] = useState(false)
  const diffing = proposal !== null && !showCurrent

  const items = useMemo(() => {
    if (!schedule) return []
    if (diffing && proposal) {
      return buildItems(proposal.blocks, calendar, { previous: schedule.blocks, changes: proposal.changes ?? [] })
    }
    return buildItems(schedule.blocks, calendar, { appliedIds: new Set(decisions.flatMap((d) => d.blockIds)) })
  }, [schedule, calendar, proposal, diffing, decisions])

  if (!schedule) return null
  const unscheduled = diffing && proposal ? (proposal.unscheduled_work ?? []) : (schedule.unscheduled_work ?? [])
  const canApply = proposal !== null && proposal.status !== 'infeasible' && proposal.validation.passed

  return (
    <Card
      id="plan"
      icon={CalendarDays}
      iconTone="sky"
      title="Weekly plan"
      subtitle={
        diffing
          ? `Proposed revision, not applied yet · compared with current plan v${schedule.schedule_version}`
          : `Current plan v${schedule.schedule_version} · times in ${tz.replace(/_/g, ' ')}`
      }
      right={
        proposal && (
          <div className="glass-segmented flex flex-wrap gap-2">
            <Button small glass active={!showCurrent} onClick={() => setShowCurrent(false)}>
              Before / after
            </Button>
            <Button small glass active={showCurrent} onClick={() => setShowCurrent(true)}>
              Current only
            </Button>
          </div>
        )
      }
    >
      <div className="space-y-4">
        {proposal && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl neu-notice neu-notice--warn px-4 py-3">
            <span className="text-sm font-semibold text-warning">Coach proposal</span>
            <Chip tone={proposal.status === 'feasible' ? 'good' : 'bad'}>{proposal.status}</Chip>
            <Chip tone={proposal.validation.passed ? 'good' : 'bad'}>
              scheduler checks {proposal.validation.passed ? 'passed' : 'failed'}
            </Chip>
            <div className="ml-auto flex gap-2">
              <Button onClick={ff.dismissJob} disabled={ff.applying}>
                Dismiss
              </Button>
              <Button
                tone="success"
                onClick={() => void ff.applyProposal()}
                disabled={!canApply || ff.applying}
                title={canApply ? undefined : 'This proposal cannot be applied'}
              >
                {ff.applying ? 'Applying…' : proposal.status === 'partial' ? 'Apply partial plan' : 'Apply'}
              </Button>
            </div>
          </div>
        )}

        <UnscheduledList work={unscheduled} calendar={calendar} tz={tz} proposed={diffing} />

        <WeekGrid items={items} tz={tz} asOf={state?.as_of ?? null} running={ff.replay?.state === 'running'} onBlockClick={props.onWhy} />
        <PlanLegend />

        {diffing && proposal && (
          <div>
            <Label>What changes</Label>
            <ChangeList
              changes={proposal.changes ?? []}
              before={schedule.blocks}
              after={proposal.blocks}
              calendar={calendar}
              tz={tz}
            />
          </div>
        )}
        {!diffing && decisions.length > 0 && (
          <p className="text-xs text-secondary">
            Blocks tagged <span className="calendar-tag px-1 text-[9px] font-semibold text-ink">WHY?</span> were
            changed by the coach. Click one to see the saved explanation.
          </p>
        )}
      </div>
    </Card>
  )
}
