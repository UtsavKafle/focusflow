import { useEffect } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { X } from 'lucide-react'

const ICON_TONES = {
  indigo: 'bg-indigo-500/15 text-indigo-300',
  rose: 'bg-rose-500/15 text-rose-300',
  sky: 'bg-sky-500/15 text-sky-300',
  emerald: 'bg-emerald-500/15 text-emerald-300',
  amber: 'bg-amber-500/15 text-amber-300',
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
    <section id={props.id} className="rounded-2xl bg-panel/90 p-5 shadow-lg shadow-black/20 ring-1 ring-white/10 backdrop-blur">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-3">
          {Icon && (
            <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${ICON_TONES[props.iconTone ?? 'indigo']}`}>
              <Icon size={18} aria-hidden />
            </span>
          )}
          <div>
            <h2 className="text-base font-semibold text-slate-50">{props.title}</h2>
            {props.subtitle && <p className="mt-0.5 text-xs text-slate-400">{props.subtitle}</p>}
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
  return <h3 className="mb-2 text-xs font-medium text-slate-400">{props.children}</h3>
}

const CHIP_TONES = {
  neutral: 'bg-white/10 text-slate-200',
  alert: 'bg-amber-400/15 text-amber-200',
  good: 'bg-emerald-400/15 text-emerald-200',
  bad: 'bg-rose-400/15 text-rose-200',
  info: 'bg-sky-400/15 text-sky-200',
}

export function Chip(props: { tone?: keyof typeof CHIP_TONES; title?: string; children: ReactNode }) {
  return (
    <span
      title={props.title}
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${CHIP_TONES[props.tone ?? 'neutral']}`}
    >
      {props.children}
    </span>
  )
}

const BUTTON_TONES = {
  primary: 'bg-indigo-500 text-white hover:bg-indigo-400 border-transparent shadow-lg shadow-indigo-500/25',
  success: 'bg-emerald-500 text-white hover:bg-emerald-400 border-transparent',
  plain: 'bg-white/5 text-slate-200 hover:bg-white/10 border-white/10',
}

export function Button(props: {
  tone?: keyof typeof BUTTON_TONES
  small?: boolean
  active?: boolean
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
      className={`rounded-lg border font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 disabled:cursor-not-allowed disabled:opacity-50 ${
        props.small ? 'px-2.5 py-1 text-xs' : 'px-4 py-2 text-sm'
      } ${props.active ? 'border-transparent bg-slate-100 text-slate-900' : BUTTON_TONES[props.tone ?? 'plain']}`}
    >
      {props.children}
    </button>
  )
}

/** Centered pop-up. Closes on Escape, on the backdrop, or with the close button. */
export function Modal(props: { title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode }) {
  const { onClose } = props
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[10vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={props.title}
        className="w-full max-w-xl rounded-2xl bg-panel p-6 shadow-2xl shadow-black/50 ring-1 ring-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-50">{props.title}</h2>
            {props.subtitle && <p className="mt-0.5 text-xs text-slate-400">{props.subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg px-2 py-1 text-slate-400 hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-indigo-400"
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
    <div className="space-y-2 text-sm leading-relaxed text-slate-200">
      {lines.map((line, i) => {
        const m = /^([A-Z][A-Za-z/ ]{2,24}):\s+(.+)$/.exec(line)
        return m ? (
          <div key={i}>
            <div className="text-[11px] font-semibold tracking-wide text-indigo-300 uppercase">{m[1]}</div>
            <p>{m[2]}</p>
          </div>
        ) : (
          <p key={i}>{line}</p>
        )
      })}
    </div>
  )
}
