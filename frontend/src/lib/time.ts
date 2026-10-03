// API times are RFC 3339 UTC. Everything on screen is shown in the scenario timezone
// and relative to the replay clock (`as_of`), never the browser clock or browser zone.

const FALLBACK_TZ = 'America/New_York'
const cache = new Map<string, Intl.DateTimeFormat>()

export function safeTz(tz: string | null | undefined): string {
  if (!tz) return FALLBACK_TZ
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz })
    return tz
  } catch {
    return FALLBACK_TZ
  }
}

function fmt(tz: string, key: string, opts: Intl.DateTimeFormatOptions) {
  const k = `${tz}|${key}`
  let f = cache.get(k)
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', { timeZone: tz, ...opts })
    cache.set(k, f)
  }
  return f
}

/** Epoch ms, or null if the value is missing or unparseable. */
export function ms(iso: string | number | null | undefined): number | null {
  if (iso === null || iso === undefined) return null
  const t = typeof iso === 'number' ? iso : Date.parse(iso)
  return Number.isFinite(t) ? t : null
}

/** Local calendar day ("YYYY-MM-DD") and minute of day for an instant, in `tz`. */
export function localParts(t: number, tz: string): { dayKey: string; minutes: number } {
  const parts = fmt(tz, 'parts', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(t)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00'
  return {
    dayKey: `${get('year')}-${get('month')}-${get('day')}`,
    minutes: Number(get('hour')) * 60 + Number(get('minute')),
  }
}

export function fmtTime(iso: string | number | null | undefined, tz: string): string {
  const t = ms(iso)
  return t === null ? 'unknown time' : fmt(tz, 'time', { hour: 'numeric', minute: '2-digit' }).format(t)
}

export function fmtDayTime(iso: string | number | null | undefined, tz: string): string {
  const t = ms(iso)
  return t === null
    ? 'unknown time'
    : fmt(tz, 'daytime', { weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(t)
}

export function fmtFull(iso: string | number | null | undefined, tz: string): string {
  const t = ms(iso)
  return t === null
    ? 'unknown time'
    : fmt(tz, 'full', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      }).format(t)
}

export function fmtRange(start: string | number, end: string | number, tz: string): string {
  return `${fmtDayTime(start, tz)} – ${fmtTime(end, tz)}`
}

/** "Mon Oct 12" for a local day key. */
export function fmtDayKey(dayKey: string): string {
  const [y, m, d] = dayKey.split('-').map(Number)
  return fmt('UTC', 'daykey', { weekday: 'short', month: 'short', day: 'numeric' }).format(
    Date.UTC(y, m - 1, d),
  )
}

/** Every local day from `first` to `last` inclusive (pure calendar arithmetic). */
export function dayRange(first: string, last: string): string[] {
  const out: string[] = []
  const [y, m, d] = first.split('-').map(Number)
  let t = Date.UTC(y, m - 1, d)
  for (let i = 0; i < 14; i++) {
    const key = new Date(t).toISOString().slice(0, 10)
    out.push(key)
    if (key >= last) break
    t += 86_400_000
  }
  return out
}

export function fmtMinutes(min: number): string {
  const h = Math.floor(min / 60)
  const m = Math.round(min % 60)
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m} min`
}
