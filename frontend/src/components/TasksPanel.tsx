import { ListChecks } from 'lucide-react'
import { useState } from 'react'
import type { FocusFlow } from '../hooks/useFocusFlow'
import { fmtDayTime, fmtMinutes } from '../lib/time'
import { Button, Card, Chip } from './ui'

const STEPS = [15, 30]

export function TasksPanel(props: { ff: FocusFlow; tz: string }) {
  const { ff, tz } = props
  const [busy, setBusy] = useState<string | null>(null)
  const calendar = ff.calendar
  if (!calendar) return null
  const overdue = new Set(ff.state?.academic.overdue_task_ids ?? [])

  const mark = async (taskId: string, minutes: number) => {
    setBusy(taskId)
    try {
      await ff.markProgress(taskId, minutes)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card id="tasks" icon={ListChecks} iconTone="amber" title="Tasks" subtitle="Synthetic exam-week workload">
      {calendar.tasks.length === 0 ? (
        <p className="text-sm text-secondary">No tasks.</p>
      ) : (
        <ul className="space-y-4">
          {calendar.tasks.map((t) => {
            const done = t.status === 'done' || t.remaining_minutes === 0
            return (
              <li key={t.task_id} className="neu-list-item flex flex-wrap items-center gap-x-3 gap-y-3">
                <div className="min-w-0 flex-1">
                  <div className={`text-sm font-medium ${done ? 'text-muted line-through' : 'text-ink'}`}>{t.title}</div>
                  <div className="text-xs text-secondary">
                    {done ? 'done' : `${fmtMinutes(t.remaining_minutes)} left`} · due {fmtDayTime(t.deadline, tz)}
                  </div>
                </div>
                {overdue.has(t.task_id) && <Chip tone="bad">overdue</Chip>}
                {!done && (
                  <div className="flex flex-wrap items-center gap-2">
                    {STEPS.map((m) => (
                      <Button key={m} small glass disabled={busy !== null} onClick={() => void mark(t.task_id, m)}>
                        +{m} min done
                      </Button>
                    ))}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
