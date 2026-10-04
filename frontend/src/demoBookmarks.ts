// Prepared replay bookmarks for the demo panel (sent as ReplayStartRequest.bookmark).
// These match the SYNTHETIC FIXTURE run (2026-10-12 evening, America/New_York).
// TODO(frontend): replace with bookmarks for the real recording once Data A picks the segment.
export interface Bookmark {
  label: string
  at: string // RFC 3339 UTC
}

export const BOOKMARKS: Bookmark[] = [
  { label: 'Evening start', at: '2026-10-13T01:50:00Z' },
  { label: 'Load rising', at: '2026-10-13T02:30:00Z' },
  { label: 'Decision point', at: '2026-10-13T02:50:00Z' },
  { label: 'Late night', at: '2026-10-13T03:20:00Z' },
]

export const SCENARIOS = ['normal', 'trigger', 'missing_data', 'infeasible']
export const SPEEDS = [1, 10, 60, 300]
