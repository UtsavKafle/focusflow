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
  const atEnd =
    replay?.state === 'paused' &&
    replay?.data_end_time != null &&
    replay?.published_time != null &&
    new Date(replay.published_time) >= new Date(replay.data_end_time)

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
      <dt className="text-[11px] text-secondary">{label}</dt>
      <dd className="text-sm font-semibold text-ink">{value}</dd>
    </div>
  )

  return (
    <Modal
      title="Demo replay"
      subtitle="Speed and scenario take effect on the next Play or Jump. Play always starts from the beginning of the segment."
      onClose={props.onClose}
    >
      <div className="space-y-5">
        {atEnd && (
          <div className="rounded-xl neu-notice neu-notice--warn p-3 text-sm font-semibold text-warning">
            End of replay data -- reached the last recorded minute for this run. Jump to an earlier
            bookmark or Reset to replay from the start.
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 rounded-xl neu-inset p-4">
          {stat('Status', atEnd ? 'paused (end of data)' : (replay?.state ?? 'unknown'))}
          {stat('Speed', speed === null ? 'unknown' : `${speed}x`)}
          {stat('Pipeline lag', lag === null ? 'unknown' : `${lag.toFixed(0)} s`)}
          {stat('Published up to', replay?.published_time ? fmtDayTime(replay.published_time, tz) : 'unknown')}
          {stat('Processed up to', replay?.processed_time ? fmtDayTime(replay.processed_time, tz) : 'unknown')}
          {stat('Data ends', replay?.data_end_time ? fmtDayTime(replay.data_end_time, tz) : 'unknown')}
          {stat('Run', replay?.run_id ?? health?.run_id ?? 'none')}
        </dl>

        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <label className="block">
            <Label>Scenario</Label>
            <select
              value={selected}
              onChange={(e) => setScenario(e.target.value)}
              className="neu-input glass-input"
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
            <div className="glass-segmented flex flex-wrap gap-2">
              {SPEEDS.map((s) => (
                <Button key={s} small glass active={ff.speed === s} onClick={() => ff.setSpeed(s)}>
                  {s}x
                </Button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button tone="primary" disabled={busy} onClick={() => void run(() => ff.replayStart(selected, BOOKMARKS[0]?.at))}>
            Play from start
          </Button>
          <Button glass disabled={busy || replay?.state !== 'running'} onClick={() => void run(ff.replayPause)}>
            Pause
          </Button>
          <Button glass disabled={busy} onClick={() => void run(ff.replayReset)}>
            Reset
          </Button>
          {isMock && (
            <Button glass disabled={busy} onClick={() => void run(ff.mockStep)} title="Fixture mode only: advance the replay by one state (5 replay minutes)">
              Step +1
            </Button>
          )}
        </div>

        <div role="group" aria-label="Bookmarks">
          <Label>Jump to a prepared moment</Label>
          <div className="flex flex-wrap gap-1.5">
            {BOOKMARKS.map((b) => (
              <Button key={b.at} small glass disabled={busy} onClick={() => void run(() => ff.replayStart(selected, b.at))}>
                {b.label} · {fmtDayTime(b.at, tz)}
              </Button>
            ))}
          </div>
        </div>

        <p className="text-[11px] text-secondary">
          {isMock
            ? 'Fixture mode: choosing another scenario starts a new run. One fixture state covers 5 replay minutes.'
            : 'The calendar and tasks are synthetic in every mode.'}
        </p>
      </div>
    </Modal>
  )
}
