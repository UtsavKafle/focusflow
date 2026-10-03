// Contract types are GENERATED from ../../../contracts/schema/*.json (`npm run types`).
// Do not hand-edit anything under ./generated. This file only re-exports under stable names.
export type {
  AcademicState,
  Quality,
  StudentState,
  Trigger,
  WearableState,
} from './generated/StudentState.schema'
export type { CalendarBundle, FixedEvent, Interval, Task } from './generated/CalendarBundle.schema'
export type { Schedule } from './generated/Schedule.schema'
export type {
  ErrorBody,
  ReplanJob,
  ScheduleBlock,
  ScheduleChange,
  ScheduleProposal,
  UnscheduledWork1 as UnscheduledWork,
} from './generated/ReplanJob.schema'
export type { ReplanRequest } from './generated/ReplanRequest.schema'
export type { ApplyRequest } from './generated/ApplyRequest.schema'
export type { ChatRequest } from './generated/ChatRequest.schema'
export type { TaskProgressRequest } from './generated/TaskProgressRequest.schema'
export type { ReplayStartRequest } from './generated/ReplayStartRequest.schema'
export type { ReplayStatus } from './generated/ReplayStatus.schema'
export type { SSEEvent } from './generated/SSEEvent.schema'

import type { ScheduleProposal } from './generated/ReplanJob.schema'
import type { ReplayStatus } from './generated/ReplayStatus.schema'
import type { StudentState } from './generated/StudentState.schema'

// ---------------------------------------------------------------------------
// Response envelopes that contracts/API.md + CHANGELOG #13/#14 describe in prose but
// that have no JSON schema. Kept loose on purpose (every extra field optional).
// ---------------------------------------------------------------------------
export type Mode = ReplayStatus['mode']
export type SourceKind = StudentState['source_kind']

export interface Health {
  ok: boolean
  mode: Mode
  data_source?: string | null
  scenario?: string | null
  label?: string | null
  run_id?: string | null
}

export interface HistoryWindow {
  window_start: string
  window_end: string
  heart_rate_bpm?: number | null
  physiological_load?: number | null
  activity_level?: number | null
  quality?: unknown
  evidence_id?: string | null
}

export interface HistoryResponse {
  schema_version?: string
  source_kind?: SourceKind | null
  windows: HistoryWindow[]
}

/** Saved decision record; decision_id == job_id (CHANGELOG #13). */
export interface Decision {
  decision_id?: string
  state_id?: string | null
  rule_version?: string | null
  model_id?: string | null
  explanation_kind?: string | null // llm | fallback
  before_version?: number | null
  after_version?: number | null // null until applied
  evidence_ids?: string[]
  tool_results?: { tool?: string; [k: string]: unknown }[]
  proposal?: ScheduleProposal | null
  explanation?: string | null
  [k: string]: unknown
}

export interface ChatResponse {
  answer: string
  evidence_ids?: string[]
  decision_id?: string | null
  kind?: string | null // saved | llm | fallback
  [k: string]: unknown
}
