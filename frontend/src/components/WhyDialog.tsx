import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { reasonLabel, TOOL_LABEL } from '../lib/format'
import type { Decision } from '../types'
import { Chip, ExplanationText, Modal } from './ui'

/** "Why did this change?": the saved explanation for an applied decision. */
export function WhyDialog(props: { decisionId: string; blockId: string; onClose: () => void }) {
  const { decisionId, blockId, onClose } = props
  const [decision, setDecision] = useState<Decision | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api
      .decision(decisionId)
      .then((d) => live && setDecision(d))
      .catch((e) => live && setError(errorMessage(e)))
    return () => {
      live = false
    }
  }, [decisionId])

  const changes = (decision?.proposal?.changes ?? []).filter((c) => (c.new_block_ids ?? []).includes(blockId))
  const tools = (decision?.tool_results ?? [])
    .map((t) => t.tool)
    .filter((t): t is string => typeof t === 'string' && !t.startsWith('_'))

  return (
    <Modal title="Why did this change?" subtitle={`Saved decision ${decisionId}`} onClose={onClose}>
      {error && <p className="text-sm text-danger">The saved decision could not be loaded: {error}</p>}
      {!error && !decision && <p className="text-sm text-secondary">Loading saved explanation…</p>}
      {decision && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-1.5">
            {changes.map((c) => (
              <Chip key={c.change_id} tone="alert">
                {c.action} · {reasonLabel(c.reason_code)}
              </Chip>
            ))}
            {decision.explanation_kind === 'fallback' && <Chip tone="alert">fallback explanation</Chip>}
          </div>
          <ExplanationText text={decision.explanation || 'No explanation was saved with this decision.'} />
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-xl neu-inset p-3 text-xs text-secondary">
            <dt>Schedule</dt>
            <dd>
              v{decision.before_version ?? '?'} →{' '}
              {typeof decision.after_version === 'number' ? `v${decision.after_version}` : 'not applied'}
            </dd>
            <dt>Trigger rules</dt>
            <dd>{decision.rule_version ?? 'unknown'}</dd>
            <dt>Evidence</dt>
            <dd>{(decision.evidence_ids ?? []).join(', ') || 'none recorded'}</dd>
            <dt>Coach steps</dt>
            <dd>{tools.map((t) => TOOL_LABEL[t] ?? t).join(' · ') || 'none recorded'}</dd>
          </dl>
        </div>
      )}
    </Modal>
  )
}
