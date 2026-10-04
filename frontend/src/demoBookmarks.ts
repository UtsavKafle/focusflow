// Prepared replay bookmarks for the demo panel (sent as ReplayStartRequest.bookmark).
// Chosen inside mock-demo-002's actual Gold data (America/New_York): Gold starts Fri Oct 9 12:01 PM,
// load is null for the first 24h (baseline warm-up), data ends Mon Oct 12 11:57 PM. The short night lands
// at Mon 8 AM (rest 474 -> 130 min, recovery 0.99 -> 0.27); load climbs through Monday afternoon/evening
// (about 0.7 by 1 PM, 1.0 by late evening); after 10 PM everything but HR is flat, so starting there (the
// old default) looked static.
export interface Bookmark {
  label: string
  at: string // RFC 3339 UTC
}

export const BOOKMARKS: Bookmark[] = [
  { label: 'Sunday night', at: '2026-10-12T01:00:00Z' }, // Sun Oct 11 9:00 PM EDT
  { label: 'Monday morning (short night)', at: '2026-10-12T10:30:00Z' }, // Mon Oct 12 6:30 AM EDT
  { label: 'Afternoon load rising', at: '2026-10-12T17:00:00Z' }, // Mon Oct 12 1:00 PM EDT
  { label: 'Decision point', at: '2026-10-13T01:30:00Z' }, // Mon Oct 12 9:30 PM EDT
]

// "Play from start" begins here, at DEFAULT_SPEED: load/rest/recovery are all still quiet this early, so
// a fast default speed gets through the quiet morning to the afternoon climb quickly.
export const DEFAULT_BOOKMARK = BOOKMARKS[1]
export const DEFAULT_SPEED = 300

export const SCENARIOS = ['normal', 'trigger', 'missing_data', 'infeasible']
export const SPEEDS = [1, 10, 60, 300]
