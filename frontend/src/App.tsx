import { useCallback, useState } from 'react'
import { CoachPanel } from './components/CoachPanel'
import { DemoPanel } from './components/DemoPanel'
import { DISCLAIMER, Header } from './components/Header'
import { PhysiologyCard } from './components/PhysiologyCard'
import { PlanCard } from './components/PlanCard'
import { TasksPanel } from './components/TasksPanel'
import { Timeline } from './components/Timeline'
import { Button } from './components/ui'
import { WhyDialog } from './components/WhyDialog'
import { useFocusFlow } from './hooks/useFocusFlow'
import { safeTz } from './lib/time'

const NOTICE_TONE = {
  info: 'neu-notice--info',
  warn: 'neu-notice--warn',
  error: 'neu-notice--error',
}

export default function App() {
  const ff = useFocusFlow()
  const { state, schedule, calendar, health, notice } = ff
  const tz = safeTz(state?.scenario_timezone ?? calendar?.timezone)
  const [why, setWhy] = useState<{ decisionId: string; blockId: string } | null>(null)
  const [demoOpen, setDemoOpen] = useState(false)

  const decisions = ff.decisions
  const onWhy = useCallback(
    (blockId: string) => {
      const d = [...decisions].reverse().find((x) => x.blockIds.includes(blockId))
      if (d) setWhy({ decisionId: d.decisionId, blockId })
    },
    [decisions],
  )

  const ready = state !== null && schedule !== null && calendar !== null

  return (
    <div className="min-h-screen">
      <Header health={health} state={state} replay={ff.replay} tz={tz} sse={ff.sse} onOpenDemo={() => setDemoOpen(true)} />

      <main className="app-main space-y-6">
        {ff.fatal && (
          <div className="flex flex-wrap items-center gap-3 rounded-2xl neu-notice neu-notice--error px-5 py-3 text-sm text-danger" role="alert">
            <span className="font-semibold">{ready ? 'Lost contact with the API; showing the last data received.' : 'Could not load !Presh.'}</span>
            <span>{ff.fatal}</span>
            <span className="ml-auto">
              <Button small onClick={() => void ff.refreshSnapshot()}>
                Retry
              </Button>
            </span>
          </div>
        )}

        {notice && (
          <div className={`neu-notice flex items-center gap-3 text-sm ${NOTICE_TONE[notice.kind]}`} role="status">
            <span>{notice.text}</span>
            <span className="ml-auto">
              <Button small onClick={() => ff.setNotice(null)}>
                Dismiss
              </Button>
            </span>
          </div>
        )}

        {!ready && !ff.fatal && (
          <div className="neu-card p-10 text-center text-secondary">
            {ff.loading
              ? 'Loading state, schedule and calendar…'
              : ff.notReady
                ? 'Waiting for the first processed wearable window of this run. Nothing is shown until real data arrives.'
                : 'Waiting for data…'}
          </div>
        )}

        {ready && (
          <>
            <div className="dashboard-grid">
              <div className="dashboard-column">
                <PhysiologyCard state={state} tz={tz} />
                <CoachPanel ff={ff} />
                <TasksPanel ff={ff} tz={tz} />
              </div>
              <div className="dashboard-column">
                <PlanCard ff={ff} tz={tz} onWhy={onWhy} />
                <Timeline
                  history={ff.history}
                  tz={tz}
                  asOf={state.as_of}
                  evidenceIds={ff.job?.evidence_ids ?? []}
                  decisions={decisions}
                />
              </div>
            </div>
          </>
        )}
      </main>

      {/* Always on screen, whatever the scroll position. */}
      <footer className="app-footer">
        {DISCLAIMER} Calendar and tasks are synthetic.
      </footer>

      {demoOpen && <DemoPanel ff={ff} tz={tz} onClose={() => setDemoOpen(false)} />}

      {why && <WhyDialog decisionId={why.decisionId} blockId={why.blockId} onClose={() => setWhy(null)} />}
    </div>
  )
}
