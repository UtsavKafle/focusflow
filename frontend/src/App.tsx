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
  info: 'ring-emerald-400/30 bg-emerald-400/10 text-emerald-100',
  warn: 'ring-amber-400/30 bg-amber-400/10 text-amber-100',
  error: 'ring-rose-400/30 bg-rose-400/10 text-rose-100',
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

      <main className="mx-auto max-w-360 space-y-5 px-5 pt-5 pb-14">
        {ff.fatal && (
          <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-rose-400/10 px-5 py-3 text-sm text-rose-100 ring-1 ring-rose-400/30" role="alert">
            <span className="font-semibold">{ready ? 'Lost contact with the API; showing the last data received.' : 'Could not load FocusFlow.'}</span>
            <span>{ff.fatal}</span>
            <span className="ml-auto">
              <Button small onClick={() => void ff.refreshSnapshot()}>
                Retry
              </Button>
            </span>
          </div>
        )}

        {notice && (
          <div className={`flex items-center gap-3 rounded-2xl px-5 py-2.5 text-sm ring-1 ${NOTICE_TONE[notice.kind]}`} role="status">
            <span>{notice.text}</span>
            <span className="ml-auto">
              <Button small onClick={() => ff.setNotice(null)}>
                Dismiss
              </Button>
            </span>
          </div>
        )}

        {!ready && !ff.fatal && (
          <div className="rounded-2xl bg-panel p-10 text-center text-slate-400 ring-1 ring-white/10">
            {ff.loading
              ? 'Loading state, schedule and calendar…'
              : ff.notReady
                ? 'Waiting for the first processed wearable window of this run. Nothing is shown until real data arrives.'
                : 'Waiting for data…'}
          </div>
        )}

        {ready && (
          <>
            <div className="grid gap-5 xl:grid-cols-12">
              <div className="space-y-5 xl:col-span-4">
                <PhysiologyCard state={state} tz={tz} />
                <CoachPanel ff={ff} />
                <TasksPanel ff={ff} tz={tz} />
              </div>
              <div className="space-y-5 xl:col-span-8">
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
      <footer className="fixed inset-x-0 bottom-0 z-20 border-t border-white/10 bg-canvas/85 px-4 py-1.5 text-center text-[11px] text-slate-400 backdrop-blur">
        {DISCLAIMER} Calendar and tasks are synthetic.
      </footer>

      {demoOpen && <DemoPanel ff={ff} tz={tz} onClose={() => setDemoOpen(false)} />}

      {why && <WhyDialog decisionId={why.decisionId} blockId={why.blockId} onClose={() => setWhy(null)} />}
    </div>
  )
}
