import { useState } from 'react'
import { BOOKMARKS, SCENARIOS, SPEEDS } from '../demoBookmarks'
import type { FocusFlow } from '../hooks/useFocusFlow'
import { num } from '../lib/format'
import { fmtDayTime } from '../lib/time'
import { Button, Label, Modal } from './ui'

/** Demo replay controls, shown as a pop-up from the header. */
export function DemoPanel(props: { ff: FocusFlow; tz: string; onClose: () => void }) {
  const { ff, tz } = props
  const { replay, health, isMock } = ff
  const [scenario, setScenario] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const selected = scenario ?? health?.scenario ?? SCENARIOS[0]
  const options = SCENARIOS.includes(selected) ? SCENARIOS : [selected, ...SCENARIOS]
  const lag = num(replay?.lag_seconds)
  const speed = num(replay?.speed)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
    }
  }

  const stat = (label: string, value: string) => (
    <div>
      <dt className="text-[11px] text-slate-400">{label}</dt>
      <dd className="text-sm font-semibold text-slate-50">{value}</dd>
    </div>
  )

  return (
    <Modal
      title="Demo replay"
      subtitle="Speed and scenario take effect on the next Play or Jump. Play always starts from the beginning of the segment."
      onClose={props.onClose}
    >
      <div className="space-y-5">
        <dl className="grid grid-cols-3 gap-x-4 gap-y-3 rounded-xl bg-white/5 p-4">
          {stat('Status', replay?.state ?? 'unknown')}
          {stat('Speed', speed === null ? 'unknown' : `${speed}x`)}
          {stat('Pipeline lag', lag === null ? 'unknown' : `${lag.toFixed(0)} s`)}
          {stat('Published up to', replay?.published_time ? fmtDayTime(replay.published_time, tz) : 'unknown')}
          {stat('Processed up to', replay?.processed_time ? fmtDayTime(replay.processed_time, tz) : 'unknown')}
          {stat('Run', replay?.run_id ?? health?.run_id ?? 'none')}
        </dl>

        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <label className="block">
            <Label>Scenario</Label>
            <select
              value={selected}
              onChange={(e) => setScenario(e.target.value)}
              className="rounded-lg border border-white/10 bg-canvas px-3 py-1.5 text-sm text-slate-50"
            >
              {options.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <div role="group" aria-label="Replay speed">
            <Label>Speed</Label>
            <div className="flex gap-1">
              {SPEEDS.map((s) => (
                <Button key={s} small active={ff.speed === s} onClick={() => ff.setSpeed(s)}>
                  {s}x
                </Button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button tone="primary" disabled={busy} onClick={() => void run(() => ff.replayStart(selected))}>
            Play from start
          </Button>
          <Button disabled={busy || replay?.state !== 'running'} onClick={() => void run(ff.replayPause)}>
            Pause
          </Button>
          <Button disabled={busy} onClick={() => void run(ff.replayReset)}>
            Reset
          </Button>
          {isMock && (
            <Button disabled={busy} onClick={() => void run(ff.mockStep)} title="Fixture mode only: advance the replay by one state (5 replay minutes)">
              Step +1
            </Button>
          )}
        </div>

        <div role="group" aria-label="Bookmarks">
          <Label>Jump to a prepared moment</Label>
          <div className="flex flex-wrap gap-1.5">
            {BOOKMARKS.map((b) => (
              <Button key={b.at} small disabled={busy} onClick={() => void run(() => ff.replayStart(selected, b.at))}>
                {b.label} · {fmtDayTime(b.at, tz)}
              </Button>
            ))}
          </div>
        </div>

        <p className="text-[11px] text-slate-400">
          {isMock
            ? 'Fixture mode: choosing another scenario starts a new run. One fixture state covers 5 replay minutes.'
            : 'The calendar and tasks are synthetic in every mode.'}
        </p>
      </div>
    </Modal>
  )
}
