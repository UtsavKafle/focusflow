import { CheckCircle2, Send, Sparkles, XCircle } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorMessage } from '../api'
import type { FocusFlow } from '../hooks/useFocusFlow'
import { num, reasonLabel, TOOL_LABEL } from '../lib/format'
import { fmtMinutes } from '../lib/time'
import type { ChatResponse, SSEEvent } from '../types'
import { Button, Card, Chip, ExplanationText, Label } from './ui'

type Payload = Record<string, unknown>
const payloadOf = (ev: SSEEvent) => (ev.payload ?? {}) as Payload
const str = (v: unknown) => (typeof v === 'string' && v.length > 0 ? v : null)

/** agent.explanation carries `kind`: "llm" | "fallback" (deterministic text, no model). */
const isFallback = (p: Payload | null | undefined) => p?.kind === 'fallback'

const CHAT_KIND: Record<string, string> = {
  saved: 'from the saved decision',
  llm: 'model answer, checked against the saved decision',
  fallback: 'fallback answer',
}

const JOB_STATUS: Record<string, string> = {
  queued: 'Queued',
  running: 'Investigating',
  ready: 'Proposal ready',
  applied: 'Applied',
  failed: 'Failed',
}

function describe(ev: SSEEvent): { text: string; failed?: boolean; hint?: string } {
  const p = payloadOf(ev)
  switch (ev.type) {
    case 'agent.started':
      return { text: 'Started investigating' }
    case 'agent.tool_result': {
      const tool = str(p.tool) ?? 'tool'
      return { text: TOOL_LABEL[tool] ?? tool, failed: p.ok === false, hint: tool }
    }
    case 'schedule.proposed':
      return { text: `Scheduler returned a ${str(p.status) ?? 'new'} proposal`, hint: str(p.proposal_id) ?? undefined }
    case 'agent.explanation':
      return { text: isFallback(p) ? 'Wrote a fallback explanation' : 'Wrote the explanation' }
    case 'schedule.applied':
      return { text: `Plan applied${num(p.schedule_version) !== null ? ` (version ${p.schedule_version})` : ''}` }
    default:
      return { text: ev.type }
  }
}

function Chat() {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [turns, setTurns] = useState<{ q: string; a?: ChatResponse; error?: string }[]>([])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const q = text.trim()
    if (!q || busy) return
    setBusy(true)
    setText('')
    try {
      // No decision_id: the backend answers from the latest saved decision of this run.
      const a = await api.chat({ message: q, decision_id: null })
      setTurns((t) => [...t, { q, a }])
    } catch (err) {
      setTurns((t) => [...t, { q, error: errorMessage(err) }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <Label>Ask about your week</Label>
      {turns.length > 0 && (
        <ul className="mb-3 max-h-72 space-y-3 overflow-y-auto">
          {turns.map((t, i) => (
            <li key={i}>
              <div className="text-sm font-medium text-ink">{t.q}</div>
              {t.a && (
                <div className="mt-1 rounded-xl neu-inset p-3">
                  <ExplanationText text={t.a.answer} />
                  {t.a.kind && (
                    <div className="mt-2">
                      <Chip tone={t.a.kind === 'fallback' ? 'alert' : 'neutral'}>{CHAT_KIND[t.a.kind] ?? t.a.kind}</Chip>
                    </div>
                  )}
                </div>
              )}
              {t.error && <div className="mt-1 text-sm text-danger">Could not get an answer: {t.error}</div>}
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Why was my Algorithms review moved?"
          aria-label="Question for the coach"
          className="neu-input glass-input min-w-0 flex-1"
        />
        <button
          type="submit"
          disabled={busy || text.trim() === ''}
          className="neu-button glass-button"
        >
          <span className="flex items-center gap-1.5">
            <Send size={14} aria-hidden />
            {busy ? 'Asking…' : 'Ask'}
          </span>
        </button>
      </form>
    </div>
  )
}

export function CoachPanel(props: { ff: FocusFlow }) {
  const { ff } = props
  const { state, job } = ff
  if (!state) return null
  const trigger = state.trigger
  const academic = state.academic
  const reasons = trigger.reason_codes ?? []
  const suppressed = trigger.suppressed_reason_codes ?? []
  const hours = num(academic.hours_until_next_exam)
  const pressure = num(academic.deadline_pressure)
  const remaining = num(academic.remaining_work_minutes)

  const log = job
    ? ff.agentEvents
        .filter((ev) => {
          const id = payloadOf(ev).job_id
          return id === job.job_id || (id === undefined && ev.type !== 'replay.updated' && ev.sequence > ff.jobSinceSeq)
        })
        .sort((a, b) => a.sequence - b.sequence)
    : []
  const explanationEvent = [...log].reverse().find((ev) => ev.type === 'agent.explanation')
  const explanation = job?.explanation ?? str(explanationEvent ? payloadOf(explanationEvent).text : null)
  const fallback =
    ff.jobDecision?.explanation_kind === 'fallback' || isFallback(explanationEvent ? payloadOf(explanationEvent) : null)
  const working = ff.replanning || job?.status === 'queued' || job?.status === 'running'

  const stat = (value: string, label: string) => (
    <div className="neu-tile">
      <div className="text-lg font-semibold text-ink tabular-nums">{value}</div>
      <div className="text-[11px] text-secondary">{label}</div>
    </div>
  )

  return (
    <Card id="coach" title="AI coach" icon={Sparkles} iconTone="indigo" subtitle={`Suggestions only, you decide · rules ${trigger.rule_version ?? 'unknown'}`}>
      <div className="space-y-5">
        <div className="grid grid-cols-1 gap-4 min-[400px]:grid-cols-3">
          {stat(hours === null ? 'unknown' : `${hours.toFixed(1)} h`, 'until next exam')}
          {stat(remaining === null ? 'unknown' : fmtMinutes(remaining), 'work remaining')}
          {stat(pressure === null ? 'unknown' : `${Math.round(pressure * 100)} / 100`, 'deadline pressure, heuristic')}
        </div>

        {trigger.replan_recommended ? (
          <div className="rounded-xl neu-notice neu-notice--warn p-4">
            <div className="text-sm font-semibold text-warning">Replan recommended</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {reasons.map((r) => (
                <Chip key={r} tone="alert" title={r}>
                  {reasonLabel(r)}
                </Chip>
              ))}
            </div>
            <div className="mt-3">
              <Button
                tone="primary"
                onClick={() => void ff.requestReplan()}
                disabled={working || reasons.length === 0 || job?.status === 'ready'}
              >
                <span className="flex items-center gap-2">
                  <Sparkles size={16} className={working ? 'animate-pulse' : ''} aria-hidden />
                  {working ? 'Coach is working…' : 'Ask coach to replan'}
                </span>
              </Button>
            </div>
          </div>
        ) : (
          <div className="rounded-xl neu-inset p-4">
            <div className="text-sm font-semibold text-ink">No replan recommended right now</div>
            {reasons.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                Signals noted
                {reasons.map((r) => (
                  <Chip key={r} title={r}>
                    {reasonLabel(r)}
                  </Chip>
                ))}
              </div>
            )}
            {suppressed.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                Held back because
                {suppressed.map((r) => (
                  <Chip key={r} tone="bad" title={r}>
                    {reasonLabel(r)}
                  </Chip>
                ))}
              </div>
            )}
          </div>
        )}

        {job && (
          <div className="space-y-4">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-medium text-secondary">What the coach did</span>
                <Chip tone={job.status === 'failed' ? 'bad' : job.status === 'applied' ? 'good' : 'info'}>
                  {JOB_STATUS[job.status] ?? job.status}
                </Chip>
              </div>
              {log.length === 0 ? (
                <p className="text-sm text-secondary">
                  {working ? 'Waiting for the first tool action…' : 'No tool actions were reported for this job.'}
                </p>
              ) : (
                <ol className="space-y-1 text-sm text-secondary">
                  {log.map((ev) => {
                    const d = describe(ev)
                    return (
                      <li key={ev.event_id} className="flex gap-2" title={d.hint}>
                        {d.failed ? (
                          <XCircle size={15} className="mt-0.5 shrink-0 text-danger" aria-hidden />
                        ) : (
                          <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-success" aria-hidden />
                        )}
                        <span>
                          {d.text}
                          {d.failed && <span className="ml-1.5 font-medium text-danger">failed</span>}
                        </span>
                      </li>
                    )
                  })}
                </ol>
              )}
              {job.status === 'failed' && (
                <div className="mt-2 rounded-xl neu-notice neu-notice--error p-3 text-sm text-danger" role="alert">
                  The coach could not produce a plan: {job.error?.message ?? 'unknown error'}
                </div>
              )}
            </div>

            {explanation && (
              <div className="rounded-xl neu-inset p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">Explanation</span>
                  {fallback && <Chip tone="alert">fallback explanation</Chip>}
                </div>
                <ExplanationText text={explanation} />
                {(job.evidence_ids ?? []).length > 0 && (
                  <div className="mt-3 text-xs text-secondary">Evidence: {(job.evidence_ids ?? []).join(', ')}</div>
                )}
                {job.status === 'ready' && !job.proposal && (
                  <p className="mt-2 text-xs text-secondary">No schedule change was proposed.</p>
                )}
              </div>
            )}
          </div>
        )}

        <Chat />
      </div>
    </Card>
  )
}
