import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { X } from 'lucide-react'

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
export function ExplanationText(props: { text: string }) {
  const lines = props.text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  return (
    <div className="space-y-2 text-sm leading-relaxed text-ink">
      {lines.map((line, i) => {
        const m = /^([A-Z][A-Za-z/ ]{2,24}):\s+(.+)$/.exec(line)
        return m ? (
          <div key={i}>
            <div className="text-[11px] font-semibold tracking-wide text-accent uppercase">{m[1]}</div>
            <p>{m[2]}</p>
          </div>
        ) : (
          <p key={i}>{line}</p>
        )
      })}
    </div>
  )
}
