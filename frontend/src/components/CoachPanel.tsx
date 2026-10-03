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
              <div className="text-sm font-medium text-slate-50">{t.q}</div>
              {t.a && (
                <div className="mt-1 rounded-xl bg-white/5 p-3">
                  <ExplanationText text={t.a.answer} />
                  {t.a.kind && (
                    <div className="mt-2">
                      <Chip tone={t.a.kind === 'fallback' ? 'alert' : 'neutral'}>{CHAT_KIND[t.a.kind] ?? t.a.kind}</Chip>
                    </div>
                  )}
                </div>
              )}
              {t.error && <div className="mt-1 text-sm text-rose-300">Could not get an answer: {t.error}</div>}
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
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-2 focus:outline-indigo-400"
        />
        <button
          type="submit"
          disabled={busy || text.trim() === ''}
          className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-white/10 disabled:opacity-50"
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
    <div className="rounded-xl bg-white/5 px-3 py-2.5 ring-1 ring-white/5">
      <div className="text-lg font-semibold text-slate-50 tabular-nums">{value}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  )

  return (
    <Card id="coach" title="AI coach" icon={Sparkles} iconTone="indigo" subtitle={`Suggestions only, you decide · rules ${trigger.rule_version ?? 'unknown'}`}>
      <div className="space-y-5">
        <div className="grid grid-cols-3 gap-3">
          {stat(hours === null ? 'unknown' : `${hours.toFixed(1)} h`, 'until next exam')}
          {stat(remaining === null ? 'unknown' : fmtMinutes(remaining), 'work remaining')}
          {stat(pressure === null ? 'unknown' : `${Math.round(pressure * 100)} / 100`, 'deadline pressure, heuristic')}
        </div>

        {trigger.replan_recommended ? (
          <div className="rounded-xl bg-linear-to-br from-amber-400/15 to-amber-400/5 p-4 ring-1 ring-amber-400/30">
            <div className="text-sm font-semibold text-amber-100">Replan recommended</div>
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
          <div className="rounded-xl bg-white/5 p-4">
            <div className="text-sm font-semibold text-slate-50">No replan recommended right now</div>
            {reasons.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                Signals noted
                {reasons.map((r) => (
                  <Chip key={r} title={r}>
                    {reasonLabel(r)}
                  </Chip>
                ))}
              </div>
            )}
            {suppressed.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
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
                <span className="text-xs font-medium text-slate-400">What the coach did</span>
                <Chip tone={job.status === 'failed' ? 'bad' : job.status === 'applied' ? 'good' : 'info'}>
                  {JOB_STATUS[job.status] ?? job.status}
                </Chip>
              </div>
              {log.length === 0 ? (
                <p className="text-sm text-slate-400">
                  {working ? 'Waiting for the first tool action…' : 'No tool actions were reported for this job.'}
                </p>
              ) : (
                <ol className="space-y-1 text-sm text-slate-300">
                  {log.map((ev) => {
                    const d = describe(ev)
                    return (
                      <li key={ev.event_id} className="flex gap-2" title={d.hint}>
                        {d.failed ? (
                          <XCircle size={15} className="mt-0.5 shrink-0 text-rose-400" aria-hidden />
                        ) : (
                          <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-400" aria-hidden />
                        )}
                        <span>
                          {d.text}
                          {d.failed && <span className="ml-1.5 font-medium text-rose-300">failed</span>}
                        </span>
                      </li>
                    )
                  })}
                </ol>
              )}
              {job.status === 'failed' && (
                <div className="mt-2 rounded-xl bg-rose-400/10 p-3 text-sm text-rose-200 ring-1 ring-rose-400/30" role="alert">
                  The coach could not produce a plan: {job.error?.message ?? 'unknown error'}
                </div>
              )}
            </div>

            {explanation && (
              <div className="rounded-xl bg-indigo-400/10 p-4 ring-1 ring-indigo-400/20">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-slate-50">Explanation</span>
                  {fallback && <Chip tone="alert">fallback explanation</Chip>}
                </div>
                <ExplanationText text={explanation} />
                {(job.evidence_ids ?? []).length > 0 && (
                  <div className="mt-3 text-xs text-slate-400">Evidence: {(job.evidence_ids ?? []).join(', ')}</div>
                )}
                {job.status === 'ready' && !job.proposal && (
                  <p className="mt-2 text-xs text-slate-400">No schedule change was proposed.</p>
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
