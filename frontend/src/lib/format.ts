import type { Mode, SourceKind } from '../types'

/** A finite number, or null. Null/undefined/NaN all mean "unknown" and must never render as 0. */
export function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** snake_case / SCREAMING_CASE machine code -> readable phrase. */
export function humanize(code: string): string {
  const s = code.replace(/_/g, ' ').toLowerCase()
  return (s.charAt(0).toUpperCase() + s.slice(1))
    .replace(/\bhr\b/gi, 'HR')
    .replace(/\beda\b/gi, 'EDA')
    .replace(/\bacc\b/gi, 'ACC')
}

export const MODE_LABEL: Record<Mode, string> = {
  synthetic_fixture: 'SYNTHETIC FIXTURE',
  live_databricks: 'LIVE DATABRICKS REPLAY',
  saved_replay: 'SAVED REPLAY',
}

export const SOURCE_LABEL: Record<SourceKind, string> = {
  synthetic_fixture: 'synthetic fixture data',
  recorded_replay: 'recorded wearable replay',
  synthetic_injection: 'recorded replay + synthetic injection',
}

export const REASON_LABEL: Record<string, string> = {
  SUSTAINED_LOAD: 'Sustained estimated load',
  LIMITED_ESTIMATED_REST: 'Limited estimated rest',
  HIGH_PRESSURE: 'High deadline pressure',
  // trigger suppression codes (contracts/CHANGELOG.md #11)
  INSUFFICIENT_DATA: 'Insufficient wearable data',
  INSUFFICIENT_BASELINE: 'Personal baseline not established yet',
  ACTIVITY_CONFOUND: 'Movement may explain the elevated load',
  RECOVERY_UNKNOWN: 'Recovery estimate unavailable',
  INSUFFICIENT_OVERNIGHT_EVIDENCE: 'Not enough overnight data',
  NO_FLEXIBLE_BLOCK: 'No movable study block',
  PENDING_DECISION: 'A proposal is already waiting for your decision',
  COOLDOWN: 'Cooling down after a recent plan change',
  AWAITING_RESET: 'Already acted on; waiting for load to settle',
  STALE_STATE: 'Wearable state is stale',
  PROTECT_REST: 'Protect rest',
  MEET_DEADLINE: 'Meet deadline',
  MAKE_ROOM: 'Make room',
  INSUFFICIENT_CAPACITY_BEFORE_DEADLINE: 'Not enough free time before the deadline',
}

/** Agent tool names (contracts/agent_tools.json) as short actions for the coach log. */
export const TOOL_LABEL: Record<string, string> = {
  get_current_student_state: 'Read current state',
  get_physiology_history: 'Reviewed recent wearable history',
  compare_to_baseline: 'Compared load with personal baseline',
  get_recent_rest: 'Checked estimated rest',
  get_upcoming_deadlines: 'Checked upcoming exams and deadlines',
  get_remaining_tasks: 'Checked remaining work',
  request_schedule_replan: 'Asked the scheduler for a validated revision',
  get_schedule_change: 'Looked up the saved schedule change',
}

/** Honest wording for the active mode (docs/demo-runbook.md fallback ladder). */
export const MODE_DESCRIPTION: Record<Mode, string> = {
  synthetic_fixture: 'Synthetic fixture, not real wearable data',
  live_databricks: 'Recorded wearable replay via Databricks',
  saved_replay: 'Feature replay (saved derived results)',
}

export const reasonLabel = (code: string) => REASON_LABEL[code] ?? humanize(code)
