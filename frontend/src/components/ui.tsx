import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

type GlassVariant = 'clear' | 'regular' | 'thick'
type GlassTint = 'neutral' | 'blue' | 'green' | 'red' | 'amber'

/** Light material for controls that float above the opaque dashboard panels. */
export function GlassSurface(props: {
  variant?: GlassVariant
  tint?: GlassTint
  className?: string
  children: ReactNode
}) {
  return (
    <span className={`glass-surface glass-${props.variant ?? 'regular'} glass-tint-${props.tint ?? 'neutral'} ${props.className ?? ''}`}>
      {props.children}
    </span>
  )
}

const ICON_TONES = {
  indigo: 'text-accent',
  rose: 'text-danger',
  sky: 'text-accent',
  emerald: 'text-success',
  amber: 'text-warning',
}

export function Card(props: {
  id?: string
  title: string
  icon?: LucideIcon
  iconTone?: keyof typeof ICON_TONES
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
}) {
  const Icon = props.icon
  return (
    <section id={props.id} className="neu-card">
      <header className="neu-card-header flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          {Icon && (
            <span className={`neu-icon panel-icon ${ICON_TONES[props.iconTone ?? 'indigo']}`}>
              <Icon size={18} aria-hidden />
            </span>
          )}
          <div>
            <h2 className="text-base font-semibold text-ink">{props.title}</h2>
            {props.subtitle && <p className="mt-0.5 text-xs text-secondary">{props.subtitle}</p>}
          </div>
        </div>
        {props.right}
      </header>
      {props.children}
    </section>
  )
}

/** Small section label inside a card. */
export function Label(props: { children: ReactNode }) {
  return <h3 className="mb-2 text-xs font-medium text-secondary">{props.children}</h3>
}

const CHIP_TONES = {
  neutral: '',
  alert: 'neu-chip--alert',
  good: 'neu-chip--good',
  bad: 'neu-chip--bad',
  info: 'neu-chip--info',
}

export function Chip(props: { tone?: keyof typeof CHIP_TONES; title?: string; children: ReactNode }) {
  return (
    <span
      title={props.title}
      className={`neu-chip glass-clear ${CHIP_TONES[props.tone ?? 'neutral']}`}
    >
      {props.children}
    </span>
  )
}

const BUTTON_TONES = {
  primary: 'neu-button--primary',
  success: 'neu-button--success',
  plain: '',
}

export function Button(props: {
  tone?: keyof typeof BUTTON_TONES
  small?: boolean
  active?: boolean
  glass?: boolean
  disabled?: boolean
  title?: string
  onClick?: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={props.title}
      disabled={props.disabled}
      aria-pressed={props.active}
      onClick={props.onClick}
      className={`neu-button ${props.small ? 'neu-button--small' : ''} ${props.glass || props.tone === 'primary' || props.tone === 'success' ? 'glass-button' : ''} ${BUTTON_TONES[props.tone ?? 'plain']}`}
    >
      {props.children}
    </button>
  )
}

/** Centered pop-up. Closes on Escape, on the backdrop, or with the close button. */
export function Modal(props: { title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode }) {
  const { onClose } = props
  const dialogRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      previousFocus?.focus()
    }
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="neu-modal-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key !== 'Tab') return
          const controls = dialogRef.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]',
          )
          if (!controls?.length) { event.preventDefault(); return }
          const first = controls[0]
          const last = controls[controls.length - 1]
          if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
            event.preventDefault()
            last.focus()
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault()
            first.focus()
          }
        }}
        role="dialog"
        aria-modal="true"
        aria-label={props.title}
        className="neu-modal glass-thick"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-ink">{props.title}</h2>
            {props.subtitle && <p className="mt-0.5 text-xs text-secondary">{props.subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="neu-button glass-button glass-icon-button shrink-0"
          >
            <X size={18} aria-hidden />
          </button>
        </div>
        {props.children}
      </div>
    </div>
  )
}

/**
 * Coach text. The deterministic explanation comes as "Section: text" lines
 * (Observation / Uncertainty / Planning reason / Action/status); anything else renders as plain paragraphs.
 */
// Matches a section header with or without a markdown "##" prefix the model may add (e.g. both
// "Status:" and "## Status:"), so headers render as styled labels, never literal "##" text.
const SECTION_HEADER_RE = /^#{0,3}\s*([A-Z][A-Za-z/ ']{2,34}):\s*(.*)$/

/** Groups lines into (label, body) sections -- a header's body may continue on following lines until the
 * next header, which is how real model output (and the deterministic fallback) is shaped. */
function sectionize(text: string): { label: string | null; body: string }[] {
  const sections: { label: string | null; body: string[] }[] = [{ label: null, body: [] }]
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const m = SECTION_HEADER_RE.exec(line)
    if (m) {
      sections.push({ label: m[1], body: m[2] ? [m[2]] : [] })
    } else {
      sections[sections.length - 1].body.push(line)
    }
  }
  return sections.filter((s) => s.label || s.body.length).map((s) => ({ label: s.label, body: s.body.join('\n') }))
}

/** Renders an explanation (LLM or the deterministic fallback) as styled section blocks, with each
 * section's body run through a real markdown renderer -- headers, bold and lists render properly, never
 * as literal "##"/"**" text. */
export function ExplanationText(props: { text: string }) {
  const sections = sectionize(props.text)
  return (
    <div className="space-y-3 text-sm leading-relaxed text-ink">
      {sections.map((s, i) => (
        <div key={i}>
          {s.label && <div className="text-[11px] font-semibold tracking-wide text-accent uppercase">{s.label}</div>}
          <div className="explanation-markdown [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:font-semibold [&_em]:italic">
            <ReactMarkdown>{s.body}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  )
}
