// Thin client for contracts/API.md. All paths are relative so the Vite proxy (dev)
// or a same-origin static deployment (prod) both work.
import type {
  ApplyRequest,
  CalendarBundle,
  ChatRequest,
  ChatResponse,
  Decision,
  Health,
  HistoryResponse,
  ReplanJob,
  ReplanRequest,
  ReplayStartRequest,
  ReplayStatus,
  Schedule,
  StudentState,
  TaskProgressRequest,
} from './types'

export class ApiError extends Error {
  status: number
  code: string
  retryable: boolean

  constructor(status: number, code: string, message: string, retryable = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the !Presh API. Is the backend running?', true)
  }
  if (!res.ok) {
    let code = `HTTP_${res.status}`
    let message = res.statusText || 'Request failed'
    let retryable = false
    try {
      const body = await res.json()
      if (typeof body?.code === 'string') code = body.code
      if (typeof body?.message === 'string') message = body.message
      else if (body?.detail) message = JSON.stringify(body.detail)
      retryable = body?.retryable === true
    } catch {
      // non-JSON error body (e.g. proxy error page): keep the status text
    }
    throw new ApiError(res.status, code, message, retryable)
  }
  return (await res.json()) as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const isStale = (e: unknown) => e instanceof ApiError && e.status === 409
export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e))

export const api = {
  health: () => request<Health>('/api/health'),
  state: () => request<StudentState>('/api/state'),
  schedule: () => request<Schedule>('/api/schedule'),
  calendar: () => request<CalendarBundle>('/api/calendar'),
  history: (end?: string) =>
    request<HistoryResponse>(`/api/history${end ? `?end=${encodeURIComponent(end)}` : ''}`),
  replan: (body: ReplanRequest) => post<{ job_id: string }>('/api/replan', body),
  job: (jobId: string) => request<ReplanJob>(`/api/replans/${encodeURIComponent(jobId)}`),
  apply: (jobId: string, body: ApplyRequest) =>
    post<Schedule>(`/api/replans/${encodeURIComponent(jobId)}/apply`, body),
  decision: (id: string) => request<Decision>(`/api/decisions/${encodeURIComponent(id)}`),
  chat: (body: ChatRequest) => post<ChatResponse>('/api/chat', body),
  progress: (taskId: string, body: TaskProgressRequest) =>
    post<CalendarBundle>(`/api/tasks/${encodeURIComponent(taskId)}/progress`, body),
  replayStart: (body: ReplayStartRequest) => post<{ run_id: string }>('/api/replay/start', body),
  replayPause: () => post<ReplayStatus>('/api/replay/pause'),
  replayReset: () => post<ReplayStatus>('/api/replay/reset'),
  replayStatus: () => request<ReplayStatus>('/api/replay/status'),
  // MOCK ONLY: only called when mode is synthetic_fixture
  mockAdvance: (n = 1) => post<{ cursor: number; of: number }>(`/api/mock/advance?n=${n}`),
}
