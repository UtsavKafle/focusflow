import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, errorMessage, isStale } from '../api'
import type {
  CalendarBundle,
  Decision,
  Health,
  HistoryResponse,
  ReplanJob,
  ReplanRequest,
  ReplayStatus,
  Schedule,
  SSEEvent,
  StudentState,
} from '../types'

export interface Notice {
  kind: 'info' | 'warn' | 'error'
  text: string
}

/** An applied proposal seen in this browser session; lets "Why did this change?" find its decision. */
export interface AppliedDecision {
  decisionId: string // == job_id (contracts/CHANGELOG.md #13)
  runId: string
  blockIds: string[]
  appliedAsOf: string | null
}

export type SseStatus = 'connecting' | 'open' | 'reconnecting'

const SSE_TYPES = [
  'state.updated',
  'replay.updated',
  'agent.started',
  'agent.tool_result',
  'schedule.proposed',
  'schedule.applied',
  'agent.explanation',
  'pipeline.error',
]
const DECISIONS_KEY = 'focusflow.decisions'
const TERMINAL = new Set(['ready', 'failed', 'applied'])

const sleep = (t: number) => new Promise((r) => setTimeout(r, t))

function loadDecisions(): AppliedDecision[] {
  try {
    const raw = JSON.parse(sessionStorage.getItem(DECISIONS_KEY) ?? '[]')
    return Array.isArray(raw) ? raw.filter((d) => typeof d?.runId === 'string') : []
  } catch {
    return []
  }
}

export function useFocusFlow() {
  const [health, setHealth] = useState<Health | null>(null)
  const [state, setState] = useState<StudentState | null>(null)
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [calendar, setCalendar] = useState<CalendarBundle | null>(null)
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [replay, setReplay] = useState<ReplayStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [fatal, setFatal] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [sse, setSse] = useState<SseStatus>('connecting')
  const [notReady, setNotReady] = useState(false)
  const [job, setJob] = useState<ReplanJob | null>(null)
  const [jobDecision, setJobDecision] = useState<Decision | null>(null)
  const [jobSinceSeq, setJobSinceSeq] = useState(0)
  const [replanning, setReplanning] = useState(false)
  const [applying, setApplying] = useState(false)
  const [agentEvents, setAgentEvents] = useState<SSEEvent[]>([])
  const [allDecisions, setDecisions] = useState<AppliedDecision[]>(loadDecisions)
  const [speed, setSpeed] = useState(60)

  const jobIdRef = useRef<string | null>(null)
  const maxSeqRef = useRef(0)

  useEffect(() => {
    try {
      sessionStorage.setItem(DECISIONS_KEY, JSON.stringify(allDecisions))
    } catch {
      // storage unavailable: decisions just do not survive a reload
    }
  }, [allDecisions])

  // ---- snapshots -----------------------------------------------------------
  const refreshState = useCallback(async () => {
    let s: StudentState
    try {
      s = await api.state()
    } catch (e) {
      // 503 STATE_NOT_READY: the run exists but no wearable row has been processed yet. Not an error.
      if (e instanceof ApiError && e.code === 'STATE_NOT_READY') {
        setState(null)
        setHistory(null)
        setNotReady(true)
        setReplay(await api.replayStatus().catch(() => null))
        return
      }
      throw e
    }
    setNotReady(false)
    setState(s)
    // History is cut at the replay clock so the timeline never shows "future" windows.
    const [h, r] = await Promise.all([
      api.history(s.as_of).catch(() => null),
      api.replayStatus().catch(() => null),
    ])
    if (h) setHistory(h)
    if (r) setReplay(r)
  }, [])

  const refreshSnapshot = useCallback(async () => {
    try {
      const [h, sch, cal] = await Promise.all([api.health(), api.schedule(), api.calendar()])
      setHealth(h)
      setSchedule(sch)
      setCalendar(cal)
      await refreshState()
      setFatal(null)
    } catch (e) {
      setFatal(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [refreshState])

  const fetchJob = useCallback(async (jobId: string) => {
    const j = await api.job(jobId)
    if (jobIdRef.current !== jobId) return j
    setJob(j)
    if (j.status === 'ready' || j.status === 'applied') {
      // The saved decision says whether the explanation is a fallback and which tools ran.
      const d = await api.decision(jobId).catch(() => null)
      if (d && jobIdRef.current === jobId) setJobDecision(d)
    }
    return j
  }, [])

  useEffect(() => {
    void refreshSnapshot()
  }, [refreshSnapshot])

  // Poll while the backend has no wearable state yet (SSE will also announce the first one).
  useEffect(() => {
    if (!notReady) return
    const id = setInterval(() => void refreshState().catch(() => undefined), 3000)
    return () => clearInterval(id)
  }, [notReady, refreshState])

  // A reset or scenario switch starts a new run: any open job belongs to the old one.
  const runId = state?.run_id ?? health?.run_id ?? null
  const lastRunRef = useRef<string | null>(null)
  useEffect(() => {
    if (runId === null) return
    if (lastRunRef.current !== null && lastRunRef.current !== runId) {
      jobIdRef.current = null
      setJob(null)
      setJobDecision(null)
    }
    lastRunRef.current = runId
  }, [runId])

  // Remember applied jobs (manual Apply, auto-apply, or applied from another client).
  const asOf = state?.as_of ?? null
  useEffect(() => {
    if (!job || job.status !== 'applied' || !job.proposal || runId === null) return
    const blockIds = [...new Set((job.proposal.changes ?? []).flatMap((c) => c.new_block_ids ?? []))]
    setDecisions((prev) =>
      prev.some((d) => d.decisionId === job.job_id)
        ? prev
        : [...prev, { decisionId: job.job_id, runId, blockIds, appliedAsOf: asOf }],
    )
  }, [job, runId, asOf])
  const decisions = allDecisions.filter((d) => d.runId === runId)

  // ---- SSE -----------------------------------------------------------------
  // No replay cursor exists: on every (re)connect we refetch the snapshot. The server may
  // resend its backlog, so events are de-duplicated by event_id and refetches are coalesced.
  useEffect(() => {
    const es = new EventSource('/api/events')
    const seen = new Set<string>()
    const want = { snapshot: false, state: false, job: false }
    let timer: ReturnType<typeof setTimeout> | undefined

    const flush = () => {
      const w = { ...want }
      want.snapshot = want.state = want.job = false
      if (w.snapshot) void refreshSnapshot()
      else if (w.state) void refreshState().catch(() => undefined)
      if (w.job && jobIdRef.current) void fetchJob(jobIdRef.current).catch(() => undefined)
    }
    const queue = (what: keyof typeof want) => {
      want[what] = true
      clearTimeout(timer)
      timer = setTimeout(flush, 150)
    }

    const onEvent = (e: MessageEvent) => {
      let ev: SSEEvent
      try {
        ev = JSON.parse(e.data)
      } catch {
        return
      }
      if (!ev || typeof ev.type !== 'string' || seen.has(ev.event_id)) return
      seen.add(ev.event_id)
      if (typeof ev.sequence === 'number') maxSeqRef.current = Math.max(maxSeqRef.current, ev.sequence)
      const payload = (ev.payload ?? {}) as Record<string, unknown>

      switch (ev.type) {
        case 'state.updated':
          queue('state')
          break
        case 'replay.updated':
        case 'schedule.applied':
          queue('snapshot')
          if (ev.type === 'schedule.applied') queue('job')
          setAgentEvents((prev) => [...prev, ev])
          break
        case 'agent.started':
        case 'agent.tool_result':
        case 'schedule.proposed':
        case 'agent.explanation':
          setAgentEvents((prev) => [...prev, ev])
          if (payload.job_id === undefined || payload.job_id === jobIdRef.current) queue('job')
          break
        case 'pipeline.error':
          // A failed replan job reports through the job itself; do not double up with a banner.
          if (payload.job_id !== undefined && payload.job_id === jobIdRef.current) {
            queue('job')
            break
          }
          setNotice({
            kind: 'error',
            text: `Pipeline error: ${typeof payload.message === 'string' ? payload.message : 'see backend logs'}`,
          })
          break
      }
    }

    es.onopen = () => {
      setSse('open')
      queue('snapshot')
    }
    es.onerror = () => setSse('reconnecting')
    es.onmessage = onEvent
    SSE_TYPES.forEach((t) => es.addEventListener(t, onEvent as EventListener))
    return () => {
      clearTimeout(timer)
      es.close()
    }
  }, [refreshSnapshot, refreshState, fetchJob])

  // ---- replan / apply ------------------------------------------------------
  const requestReplan = useCallback(async () => {
    if (!state || !schedule || !calendar) return
    const codes = state.trigger.reason_codes ?? []
    if (codes.length === 0) return
    setReplanning(true)
    setNotice(null)
    setJob(null)
    setJobDecision(null)
    jobIdRef.current = null
    setJobSinceSeq(maxSeqRef.current)
    try {
      const { job_id } = await api.replan({
        run_id: state.run_id,
        state_id: state.state_id,
        schedule_version: schedule.schedule_version,
        calendar_version: calendar.calendar_version,
        tasks_version: calendar.tasks_version,
        reason_codes: codes as ReplanRequest['reason_codes'],
      })
      jobIdRef.current = job_id
      setJob({ job_id, status: 'queued' })
      // Poll until the job settles (SSE events also trigger a refetch; whichever lands first wins).
      for (let i = 0; i < 120 && jobIdRef.current === job_id; i++) {
        const j = await fetchJob(job_id)
        if (TERMINAL.has(j.status)) break
        await sleep(1000)
      }
    } catch (e) {
      if (isStale(e)) {
        await refreshSnapshot()
        setNotice({
          kind: 'warn',
          text: 'The plan or tasks changed since this view loaded. Everything was refreshed; ask the coach again.',
        })
      } else {
        setNotice({ kind: 'error', text: `Replan request failed: ${errorMessage(e)}` })
      }
    } finally {
      setReplanning(false)
    }
  }, [state, schedule, calendar, fetchJob, refreshSnapshot])

  const dismissJob = useCallback(() => {
    jobIdRef.current = null
    setJob(null)
    setJobDecision(null)
  }, [])

  const applyProposal = useCallback(async () => {
    const proposal = job?.proposal
    if (!job || !proposal) return
    setApplying(true)
    setNotice(null)
    try {
      // The version the proposal was computed against; the server answers 409 if the plan moved on.
      const next = await api.apply(job.job_id, { expected_schedule_version: proposal.schedule_version })
      setSchedule(next)
      setJob({ ...job, status: 'applied' })
      setNotice({ kind: 'info', text: `Plan applied (schedule version ${next.schedule_version}).` })
      void refreshState().catch(() => undefined)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'ALREADY_APPLIED') {
        await Promise.all([refreshSnapshot(), fetchJob(job.job_id).catch(() => undefined)])
        setNotice({ kind: 'info', text: 'This proposal was already applied. The current plan is shown.' })
      } else if (isStale(e)) {
        dismissJob()
        await refreshSnapshot()
        setNotice({
          kind: 'warn',
          text: 'The schedule, calendar or tasks changed after this proposal was made, so it was not applied. The latest plan is shown; ask the coach again.',
        })
      } else {
        setNotice({ kind: 'error', text: `Could not apply the plan: ${errorMessage(e)}` })
        // e.g. the job was already applied elsewhere: resync so the stale proposal goes away
        void refreshSnapshot()
        void fetchJob(job.job_id).catch(() => undefined)
      }
    } finally {
      setApplying(false)
    }
  }, [job, dismissJob, fetchJob, refreshSnapshot, refreshState])

  // ---- task progress -------------------------------------------------------
  const markProgress = useCallback(
    async (taskId: string, minutes: number) => {
      if (!calendar) return
      try {
        const cal = await api.progress(taskId, {
          completed_minutes: minutes,
          expected_tasks_version: calendar.tasks_version,
        })
        setCalendar(cal)
        void refreshState().catch(() => undefined)
      } catch (e) {
        if (isStale(e)) {
          await refreshSnapshot()
          setNotice({ kind: 'warn', text: 'Tasks changed elsewhere. Refreshed; try again.' })
        } else {
          setNotice({ kind: 'error', text: `Could not record progress: ${errorMessage(e)}` })
        }
      }
    },
    [calendar, refreshSnapshot, refreshState],
  )

  // ---- replay controls -----------------------------------------------------
  // Fixture mode is the only one that exposes /api/mock/advance.
  const isMock = health?.mode === 'synthetic_fixture' && (health.data_source ?? 'fixture') === 'fixture'

  const guard = useCallback(
    async (label: string, fn: () => Promise<void>) => {
      try {
        await fn()
      } catch (e) {
        setNotice({ kind: 'error', text: `${label} failed: ${errorMessage(e)}` })
      }
    },
    [],
  )

  const replayStart = useCallback(
    (scenarioId: string, bookmark?: string) =>
      guard('Replay start', async () => {
        // In fixture mode a different scenario_id switches the scenario and starts a new run.
        await api.replayStart({ scenario_id: scenarioId, speed, bookmark: bookmark ?? null })
        await refreshSnapshot()
      }),
    [guard, refreshSnapshot, speed],
  )

  const replayPause = useCallback(
    () => guard('Pause', async () => setReplay(await api.replayPause())),
    [guard],
  )

  const replayReset = useCallback(
    () =>
      guard('Reset', async () => {
        await api.replayReset()
        dismissJob()
        setNotice(null)
        await refreshSnapshot()
      }),
    [guard, dismissJob, refreshSnapshot],
  )

  const mockStep = useCallback(
    () =>
      guard('Step', async () => {
        await api.mockAdvance(1)
        await refreshState()
      }),
    [guard, refreshState],
  )

  return {
    health,
    state,
    schedule,
    calendar,
    history,
    replay,
    loading,
    fatal,
    notice,
    sse,
    notReady,
    job,
    jobDecision,
    jobSinceSeq,
    replanning,
    applying,
    agentEvents,
    decisions,
    speed,
    isMock,
    setSpeed,
    setNotice,
    refreshSnapshot,
    requestReplan,
    applyProposal,
    dismissJob,
    markProgress,
    replayStart,
    replayPause,
    replayReset,
    mockStep,
  }
}

export type FocusFlow = ReturnType<typeof useFocusFlow>
